# src/cli.py
"""
Simple CLI for interacting with the blockchain (Requirement 8)
Usage examples:
  python src/cli.py init
  python src/cli.py mine --miner alice
  python src/cli.py new-tx --from alice --to bob --amount 10
  python src/cli.py balance --addr alice
  python src/cli.py show-chain
  python src/cli.py show-mempool
"""
import argparse
import os
import json
from blockchain import Blockchain, Transaction

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CHAIN_PATH = os.path.join(DATA_DIR, "chain.json")
UTXO_PATH = os.path.join(DATA_DIR, "utxos.json")
os.makedirs(DATA_DIR, exist_ok=True)

def load_blockchain() -> Blockchain:
    bc = Blockchain()
    if os.path.exists(CHAIN_PATH) and os.path.exists(UTXO_PATH):
        bc.load_from_file(CHAIN_PATH, UTXO_PATH)
    return bc

def save_blockchain(bc: Blockchain):
    bc.save_to_file(CHAIN_PATH, UTXO_PATH)

def main():
    parser = argparse.ArgumentParser(description="Blockchain CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize new blockchain")

    mine_parser = subparsers.add_parser("mine", help="Mine a new block")
    mine_parser.add_argument("--miner", required=True, help="Miner address")

    tx_parser = subparsers.add_parser("new-tx", help="Create new transaction")
    tx_parser.add_argument("--from", dest="from_addr", required=True)
    tx_parser.add_argument("--to", dest="to_addr", required=True)
    tx_parser.add_argument("--amount", type=int, required=True)

    bal_parser = subparsers.add_parser("balance", help="Check address balance")
    bal_parser.add_argument("--addr", required=True)

    subparsers.add_parser("show-chain", help="Show full blockchain")
    subparsers.add_parser("show-mempool", help="Show pending transactions")

    args = parser.parse_args()
    bc = load_blockchain()

    if args.command == "init":
        bc = Blockchain()
        save_blockchain(bc)
        print("Blockchain initialized.")

    elif args.command == "mine":
        idx = bc.mine(miner_address=args.miner)
        save_blockchain(bc)
        if idx:
            print(f"Mined block #{idx}")
        else:
            print("No transactions to mine.")

    elif args.command == "new-tx":
        # Find spendable UTXO
        spendables = [((txid, idx), utxo) for (txid, idx), utxo in bc.utxos.items() if utxo["address"] == args.from_addr]
        total_amt = sum(utxo["amount"] for _, utxo in spendables)
        if not spendables:
            print("No UTXO for this address.")
            return
        if total_amt < args.amount:
            print("Insufficient balance.")
            return
        # use first UTXO only for simplicity
        (txid, idx), utxo = spendables[0]
        tx = Transaction(
            inputs=[{"txid": txid, "index": idx, "address": args.from_addr}],
            outputs=[{"amount": args.amount, "address": args.to_addr}]
        ).to_dict()
        ok = bc.add_new_transaction(tx)
        save_blockchain(bc)
        print("Transaction added." if ok else "Transaction invalid.")

    elif args.command == "balance":
        total = sum(utxo["amount"] for _, utxo in bc.utxos.items() if utxo["address"] == args.addr)
        print(f"Balance of {args.addr}: {total}")

    elif args.command == "show-chain":
        for b in bc.chain:
            print(json.dumps(b.to_dict(), indent=2, ensure_ascii=False))

    elif args.command == "show-mempool":
        print(json.dumps(bc.unconfirmed_transactions, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
