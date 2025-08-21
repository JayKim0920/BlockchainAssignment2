"""
Blockchain CLI
Usage:
python src/cli.py init
python src/cli.py mine --miner alice
python src/cli.py new-tx --from alice --to bob --amount 10
python src/cli.py show-mempool
python src/cli.py balance --addr alice
python src/cli.py balance --addr bob
"""
from __future__ import annotations
import argparse
import os
import json
from typing import Tuple

# import the revised blockchain implementation
from blockchain import Blockchain, Transaction

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
CHAIN_PATH = os.path.join(DATA_DIR, "chain.json")
UTXO_PATH = os.path.join(DATA_DIR, "utxos.json")
MEMPOOL_PATH = os.path.join(DATA_DIR, "mempool.json")
os.makedirs(DATA_DIR, exist_ok=True)


def load_blockchain() -> Blockchain:
    """Instantiate Blockchain and load persisted files if they exist."""
    bc = Blockchain(data_dir=DATA_DIR)
    # Blockchain constructor already tries to load; ensure load_from_file to be explicit
    try:
        bc.load_from_file()
    except Exception:
        pass
    return bc


def save_blockchain(bc: Blockchain):
    """Persist blockchain state (chain, utxos, mempool)."""
    bc.save_to_file()


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
        # fresh Blockchain() already creates genesis if needed
        bc = Blockchain(data_dir=DATA_DIR)
        save_blockchain(bc)
        print("Blockchain initialized.")

    elif args.command == "mine":
        idx = bc.mine(miner_address=args.miner)
        save_blockchain(bc)
        print(f"Mined block #{idx}")

    elif args.command == "new-tx":
        # Find spendable UTXOs for from_addr
        spendables = [((txid, idx), utxo) for (txid, idx), utxo in bc.utxos.items() if utxo["address"] == args.from_addr]
        total_amt = sum(utxo["amount"] for _, utxo in spendables)
        if not spendables:
            print("No UTXO for this address.")
            return
        if total_amt < args.amount:
            print("Insufficient balance.")
            return

        # Use first available UTXO (simple selection)
        (txid, idx), utxo = spendables[0]
        inputs = [{"txid": txid, "index": idx, "address": args.from_addr}]
        outputs = [{"amount": args.amount, "address": args.to_addr}]
        change = utxo["amount"] - args.amount
        if change > 0:
            outputs.append({"amount": change, "address": args.from_addr})

        tx = Transaction(inputs=inputs, outputs=outputs).to_dict()
        ok = bc.add_new_transaction(tx)
        print("Transaction added to mempool." if ok else "Transaction invalid!")
        save_blockchain(bc)

    elif args.command == "balance":
        # confirmed UTXOs
        total = sum(utxo["amount"] for _, utxo in bc.utxos.items() if utxo["address"] == args.addr)

        # adjust for unconfirmed transactions (mempool)
        for txd in bc.unconfirmed_transactions:
            # subtract spent inputs (look up amounts from confirmed UTXOs if present)
            for inp in txd["inputs"]:
                if inp["address"] == args.addr:
                    key = (inp["txid"], int(inp["index"]))
                    # if the input refers to an existing confirmed UTXO, subtract it
                    total -= bc.utxos.get(key, {}).get("amount", 0)
            # add unconfirmed outputs to address
            for out in txd["outputs"]:
                if out["address"] == args.addr:
                    total += out["amount"]

        print(f"Balance of {args.addr}: {total}")

    elif args.command == "show-chain":
        for b in bc.chain:
            print(json.dumps(b.to_dict(), indent=2, ensure_ascii=False))

    elif args.command == "show-mempool":
        if not bc.unconfirmed_transactions:
            print("Mempool is empty.")
        else:
            print(json.dumps(bc.unconfirmed_transactions, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

