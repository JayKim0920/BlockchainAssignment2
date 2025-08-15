# src/main.py
"""
Quick demo:
- Mine a block to give miner1 a coinbase reward.
- Create a spend from miner1 -> bob.
- Attempt a double-spend of the same input (should be rejected).
- Mine again to include the valid tx.
- Show that tampering invalidates the chain.
Run: python src/main.py
"""

from blockchain import Blockchain, Transaction
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)
CHAIN_PATH = os.path.join(DATA_DIR, "chain.json")
UTXO_PATH = os.path.join(DATA_DIR, "utxos.json")

def print_balances(bc: Blockchain, addresses):
    # naive balance calc by scanning UTXO set
    totals = {a: 0 for a in addresses}
    for (txid, idx), utxo in bc.utxos.items():
        addr = utxo["address"]
        if addr in totals:
            totals[addr] += int(utxo["amount"])
    print("Balances:", totals)

def find_spendable_utxos(bc: Blockchain, address: str):
    items = [((txid, idx), utxo) for (txid, idx), utxo in bc.utxos.items() if utxo["address"] == address]
    return items

def main():
    bc = Blockchain(difficulty=3, block_reward=50)

    print("Mining first block for miner1...")
    bc.mine(miner_address="miner1")
    print("Chain valid?", bc.is_chain_valid())
    print_balances(bc, ["miner1", "bob"])

    # create a tx spending miner1's UTXO to bob
    spendables = find_spendable_utxos(bc, "miner1")
    assert spendables, "no utxo for miner1"
    (txid, idx), utxo = spendables[0]

    amt = utxo["amount"]
    tx1 = Transaction(
        inputs=[{"txid": txid, "index": idx, "address": "miner1"}],
        outputs=[{"amount": amt, "address": "bob"}]
    ).to_dict()

    ok = bc.add_new_transaction(tx1)
    print("Add tx1 miner1->bob:", ok)

    # attempt a double-spend using same input again
    tx_double = Transaction(
        inputs=[{"txid": txid, "index": idx, "address": "miner1"}],
        outputs=[{"amount": amt, "address": "someone_else"}]
    ).to_dict()

    ok2 = bc.add_new_transaction(tx_double)
    print("Add double-spend tx:", ok2, "(expected False)")

    # mine a new block including tx1
    print("Mining second block for miner1...")
    bc.mine(miner_address="miner1")
    print("Chain valid?", bc.is_chain_valid())
    print_balances(bc, ["miner1", "bob"])

    # persist
    bc.save_to_file(CHAIN_PATH, UTXO_PATH)
    print("Saved to", CHAIN_PATH, "and", UTXO_PATH)

    # Tamper test: modify amount in block 1 tx (if exists) and re-check validity
    if len(bc.chain) > 1 and bc.chain[1].transactions:
        print("Tampering with block 1...")
        bc.chain[1].transactions[0]["outputs"][0]["amount"] = 9999
        print("After tamper, valid?", bc.is_chain_valid())

if __name__ == "__main__":
    main()
