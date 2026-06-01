#!/usr/bin/env python3
import os
import sys
import time
import hmac
import hashlib
import logging
import argparse
from pathlib import Path
from datetime import datetime
from urllib.parse import urlencode
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def setup_logging():
    Path("logs").mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"logs/trading_{timestamp}.log"
    
    logger = logging.getLogger("TradingBot")
    logger.setLevel(logging.DEBUG)
    
    if logger.handlers:
        logger.handlers.clear()
    
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter('%(message)s'))
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger, log_file


class BinanceClient:
    BASE_URL = "https://testnet.binancefuture.com"
    
    def __init__(self, api_key, secret_key, logger):
        self.api_key = api_key
        self.secret_key = secret_key
        self.logger = logger
        
        self.session = requests.Session()
        retries = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503])
        self.session.mount("https://", HTTPAdapter(max_retries=retries))
    
    def _sign(self, params):
        query = urlencode(params)
        return hmac.new(
            self.secret_key.encode('utf-8'),
            query.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
    
    def _request(self, method, endpoint, params=None, signed=False):
        url = f"{self.BASE_URL}{endpoint}"
        headers = {"X-MBX-APIKEY": self.api_key}
        
        if params is None:
            params = {}
        
        if signed:
            params['timestamp'] = int(time.time() * 1000)
            params['signature'] = self._sign(params)
        
        self.logger.debug(f"REQUEST: {method} {endpoint}")
        self.logger.debug(f"PARAMS: {params}")
        
        try:
            response = self.session.request(method, url, params=params, headers=headers, timeout=10)
            self.logger.debug(f"STATUS: {response.status_code}")
            self.logger.debug(f"RESPONSE: {response.text}")
            
            response.raise_for_status()
            data = response.json()
            
            if isinstance(data, dict) and 'code' in data and data['code'] < 0:
                raise Exception(f"API Error [{data['code']}]: {data.get('msg', 'Unknown')}")
            
            return data
            
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Network error: {e}")
            raise
        except Exception as e:
            self.logger.error(f"Request failed: {e}")
            raise
    
    def place_order(self, symbol, side, order_type, quantity, price=None):
        params = {
            'symbol': symbol.upper(),
            'side': side.upper(),
            'type': order_type.upper(),
            'quantity': quantity
        }
        
        if price and order_type.upper() == 'LIMIT':
            params['price'] = price
            params['timeInForce'] = 'GTC'
        
        return self._request("POST", "/fapi/v1/order", params=params, signed=True)


def validate_params(symbol, side, order_type, quantity, price):
    errors = {}
    
    if not symbol or len(symbol) < 5:
        errors['symbol'] = "Invalid symbol (e.g., BTCUSDT)"
    
    if side.upper() not in ['BUY', 'SELL']:
        errors['side'] = "Must be BUY or SELL"
    
    if order_type.upper() not in ['MARKET', 'LIMIT']:
        errors['type'] = "Must be MARKET or LIMIT"
    
    try:
        qty = float(quantity)
        if qty <= 0:
            errors['quantity'] = "Must be positive"
    except (ValueError, TypeError):
        errors['quantity'] = "Must be a valid number"
    
    if order_type.upper() == 'LIMIT':
        try:
            prc = float(price)
            if prc <= 0:
                errors['price'] = "Must be positive"
        except (ValueError, TypeError):
            errors['price'] = "Required for LIMIT orders"
    
    cleaned = {
        'symbol': symbol.upper(),
        'side': side.upper(),
        'type': order_type.upper(),
        'quantity': float(quantity) if quantity else None,
        'price': float(price) if price else None
    }
    
    return len(errors) == 0, errors, cleaned


def place_order(client, logger, params):
    print("\n" + "=" * 50)
    print("ORDER SUMMARY")
    print("=" * 50)
    print(f"Symbol    : {params['symbol']}")
    print(f"Side      : {params['side']}")
    print(f"Type      : {params['type']}")
    print(f"Quantity  : {params['quantity']}")
    if params['price']:
        print(f"Price     : ${params['price']}")
    print("=" * 50)
    
    logger.info(f"Placing {params['type']} {params['side']} order for {params['quantity']} {params['symbol']}")
    
    try:
        response = client.place_order(
            symbol=params['symbol'],
            side=params['side'],
            order_type=params['type'],
            quantity=params['quantity'],
            price=params['price']
        )
        
        print("\n" + "=" * 50)
        print("ORDER SUCCESS")
        print("=" * 50)
        print(f"Order ID    : {response.get('orderId')}")
        print(f"Status      : {response.get('status')}")
        print(f"Executed Qty: {response.get('executedQty')}")
        print(f"Avg Price   : ${response.get('avgPrice', 'N/A')}")
        print("=" * 50 + "\n")
        
        logger.info(f"Order {response.get('orderId')} - Status: {response.get('status')}")
        logger.debug(f"Full response: {response}")
        
        return True
        
    except Exception as e:
        print("\n" + "=" * 50)
        print("ORDER FAILED")
        print("=" * 50)
        print(f"Error: {str(e)}")
        print("=" * 50 + "\n")
        
        logger.error(f"Order failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Binance Futures Testnet Trading Bot")
    parser.add_argument('--symbol', required=True, help='Trading pair (e.g., BTCUSDT)')
    parser.add_argument('--side', required=True, choices=['BUY', 'SELL'])
    parser.add_argument('--type', required=True, choices=['MARKET', 'LIMIT'], help='Order type')
    parser.add_argument('--quantity', required=True, help='Order quantity')
    parser.add_argument('--price', help='Required for LIMIT orders')
    
    args = parser.parse_args()
    
    logger, log_file = setup_logging()
    
    api_key = os.getenv('BINANCE_API_KEY')
    secret_key = os.getenv('BINANCE_SECRET_KEY')
    
    if not api_key or not secret_key:
        print("\nMissing API credentials!")
        print("Set: export BINANCE_API_KEY='your_key'")
        print("    export BINANCE_SECRET_KEY='your_secret'")
        sys.exit(1)
    
    is_valid, errors, params = validate_params(
        args.symbol, args.side, args.type, args.quantity, args.price
    )
    
    if not is_valid:
        print("\nInvalid parameters:")
        for field, error in errors.items():
            print(f"  - {field}: {error}")
        sys.exit(1)
    
    client = BinanceClient(api_key, secret_key, logger)
    success = place_order(client, logger, params)
    
    print(f"Logs saved to: {log_file}")
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()