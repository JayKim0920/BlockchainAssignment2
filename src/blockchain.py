# src/blockchain.py
"""
Assignment 2 implementation (Python): Block structure + Chain integrity + Transaction handling + Double-spend prevention (UTXO)
- Block: index, timestamp, transactions, previous_hash, nonce, hash
- Transactions: UTXO-style inputs/outputs; txid = sha256 of canonical JSON
- Chain integrity: SHA-256, previous_hash linkage, PoW (configurable difficulty)
- Double-spend prevention: UTXO set; tx validation checks inputs exist & are unspent; prevent reuse within block/mempool
- Persistence: save/load chain and UTXO set to JSON
NOTE: No signatures (wallet) yet; addresses are simple strings (extension 10 can add ECDSA later).
"""

from __future__ import annotations
import hashlib
import json
import time
from typing import List, Dict, Any, Tuple, Optional


def sha256_json(obj: Any) -> str:
    s = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(s.encode()).hexdigest()


class Transaction:
    """
    UTXO-style transaction.
    inputs: list of {"txid": str, "index": int, "address": str}
    outputs: list of {"amount": int, "address": str}
    """
    def __init__(self, inputs: List[Dict[str, Any]], outputs: List[Dict[str, Any]]):
        self.inputs = inputs
        self.outputs = outputs
        self.txid = self.compute_txid()

    def to_dict(self) -> Dict[str, Any]:
        return {"txid": self.txid, "inputs": self.inputs, "outputs": self.outputs}

    def compute_txid(self) -> str:
        content = {"inputs": self.inputs, "outputs": self.outputs}
        return sha256_json(content)

    @staticmethod
    def coinbase(miner_address: str, amount: int, height: int) -> "Transaction":
        # coinbase has no inputs; include height for uniqueness
        outputs = [{"amount": amount, "address": miner_address}]
        tx = Transaction(inputs=[{"txid": "COINBASE", "index": height, "address": "COINBASE"}],
                         outputs=outputs)
        return tx


class Block:
    def __init__(self, index: int, transactions: List[Dict[str, Any]], timestamp: float,
                 previous_hash: str, nonce: int = 0):
        self.index = index
        self.transactions = transactions  # list of transaction dictionaries
        self.timestamp = timestamp
        self.previous_hash = previous_hash
        self.nonce = nonce
        self.hash = self.compute_hash()

    def compute_hash(self) -> str:
        content = {
            "index": self.index,
            "transactions": self.transactions,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
        }
        return sha256_json(content)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "transactions": self.transactions,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "hash": self.hash,
        }


class Blockchain:
    def __init__(self, difficulty: int = 3, block_reward: int = 50):
        self.unconfirmed_transactions: List[Dict[str, Any]] = []  # mempool (dict form)
        self.chain: List[Block] = []
        # UTXO set: key (transaction id, idx) -> {"amount": int, "address": str}
        self.utxos: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self.difficulty = difficulty
        self.block_reward = block_reward
        self.create_genesis_block()

    # ---------------- Basic chain operations ----------------

    def create_genesis_block(self):
        genesis = Block(0, [], time.time(), "0")
        genesis.hash = genesis.compute_hash()
        self.chain.append(genesis)

    @property
    def last_block(self) -> Block:
        return self.chain[-1]

    # ---------------- Mempool & TX handling -----------------

    def add_new_transaction(self, tx: Dict[str, Any]) -> bool:
        """
        Add a new transaction dictionary to mempool if valid against current UTXO and mempool (no double-spending!).
        """
        # Recreate obj for validation
        try:
            tx_obj = Transaction(inputs=tx["inputs"], outputs=tx["outputs"])
            if "txid" in tx and tx["txid"] != tx_obj.txid:
                return False  # malformed/forged
        except Exception:
            return False

        # Validate against a temp utxo view that includes mempool effects
        temp_utxo = self._clone_utxo()
        # Apply already accepted mempool txs to temp_utxo to prevent conflicts
        for pending in self.unconfirmed_transactions:
            ok, _ = self._validate_and_apply_to_utxo(Transaction(pending["inputs"], pending["outputs"]), temp_utxo)
            if not ok:
                pass

        ok, err = self._validate_and_apply_to_utxo(tx_obj, temp_utxo)
        if not ok:
            return False
        # If valid, append to mempool
        self.unconfirmed_transactions.append(tx_obj.to_dict())
        return True

    def _clone_utxo(self) -> Dict[Tuple[str, int], Dict[str, Any]]:
        return {k: v.copy() for k, v in self.utxos.items()}

    def _validate_and_apply_to_utxo(self, tx: Transaction, utxo_view: Dict[Tuple[str, int], Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
        if tx.inputs and tx.inputs[0].get("txid") == "COINBASE":
            return False, "coinbase not allowed in mempool"

        total_in = 0
        seen_inputs = set()
        for i in tx.inputs:
            key = (i["txid"], int(i["index"]))
            if key in seen_inputs:
                return False, "double spend within tx"
            seen_inputs.add(key)
            utxo = utxo_view.get(key)
            if utxo is None:
                return False, f"missing utxo {key}"
            if utxo["address"] != i["address"]:
                return False, "ownership mismatch"
            amt = int(utxo["amount"])
            if amt <= 0:
                return False, "invalid utxo amount"
            total_in += amt

        total_out = 0
        for o in tx.outputs:
            amt = int(o["amount"])
            if amt <= 0:
                return False, "non-positive output"
            total_out += amt

        if total_in < total_out:
            return False, "outputs exceed inputs"

        fee = total_in - total_out

        for i in tx.inputs:
            key = (i["txid"], int(i["index"]))
            utxo_view.pop(key, None)
        for idx, o in enumerate(tx.outputs):
            utxo_view[(tx.txid, idx)] = {"amount": int(o["amount"]), "address": o["address"]}
        return True, None

    # ---------------- Mining (PoW) --------------------------

    def proof_of_work(self, block: Block) -> str:
        target = "0" * self.difficulty
        block.nonce = 0
        h = block.compute_hash()
        while not h.startswith(target):
            block.nonce += 1
            h = block.compute_hash()
        block.hash = h #imply final hash to block
        return h

    def is_valid_proof(self, block: Block, block_hash: str) -> bool:
        return block_hash.startswith("0" * self.difficulty) and block_hash == block.compute_hash()

    def add_block(self, block: Block, proof: str) -> bool:
        if self.last_block.hash != block.previous_hash:
            return False
        if not self.is_valid_proof(block, proof):
            return False
        block.hash = proof #set hash to proof before appending to chain.
        temp_utxo = self._clone_utxo()
        for txd in block.transactions:
            tx = Transaction(txd["inputs"], txd["outputs"])
            if tx.inputs and tx.inputs[0].get("txid") == "COINBASE":
                if block.transactions.index(txd) != 0:
                    return False
                for idx, o in enumerate(tx.outputs):
                    temp_utxo[(tx.txid, idx)] = {"amount": int(o["amount"]), "address": o["address"]}
                continue
            ok, _ = self._validate_and_apply_to_utxo(tx, temp_utxo)
            if not ok:
                return False
        self.chain.append(block)
        self.utxos = temp_utxo
        return True

    def mine(self, miner_address: str) -> int | bool:
        if not self.unconfirmed_transactions:
            pass
        txs: List[Dict[str, Any]] = []
        coinbase_tx = Transaction.coinbase(miner_address, self.block_reward, self.last_block.index + 1)
        txs.append(coinbase_tx.to_dict())
        temp_utxo = self._clone_utxo()
        for idx, o in enumerate(coinbase_tx.outputs):
            temp_utxo[(coinbase_tx.txid, idx)] = {"amount": int(o["amount"]), "address": o["address"]}
        included = []
        for txd in self.unconfirmed_transactions:
            tx = Transaction(txd["inputs"], txd["outputs"])
            ok, _ = self._validate_and_apply_to_utxo(tx, temp_utxo)
            if ok:
                included.append(txd)
        txs.extend(included)
        new_block = Block(index=self.last_block.index + 1,
                          transactions=txs,
                          timestamp=time.time(),
                          previous_hash=self.last_block.hash)
        proof = self.proof_of_work(new_block)
        if not self.add_block(new_block, proof):
            return False
        self.unconfirmed_transactions = [
            t for t in self.unconfirmed_transactions if t not in included
        ]
        return new_block.index

    # ---------------- Validation & persistence --------------

    def is_chain_valid(self) -> bool:
        temp_utxo: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for i in range(len(self.chain)):
            b = self.chain[i]
            if i == 0:
                if b.previous_hash != "0":
                    return False
                if b.compute_hash() != b.hash:
                    return False
                continue
            prev = self.chain[i - 1]
            # ---- timestamp check in ascending order ----
            if b.timestamp < prev.timestamp:
                return False
            # ------------------------------------
            if b.previous_hash != prev.hash:
                return False
            if b.compute_hash() != b.hash:
                return False
            if not b.hash.startswith("0" * self.difficulty):
                return False
            for idx_tx, txd in enumerate(b.transactions):
                tx = Transaction(txd["inputs"], txd["outputs"])
                if tx.inputs and tx.inputs[0].get("txid") == "COINBASE":
                    if idx_tx != 0:
                        return False
                    for out_index, o in enumerate(tx.outputs):
                        temp_utxo[(tx.txid, out_index)] = {"amount": int(o["amount"]), "address": o["address"]}
                    continue
                ok, _ = self._validate_and_apply_to_utxo(tx, temp_utxo)
                if not ok:
                    return False
        return True

    def save_to_file(self, chain_path: str, utxo_path: str):
        chain_data = [b.to_dict() for b in self.chain]
        with open(chain_path, "w", encoding="utf-8") as f:
            json.dump(chain_data, f, ensure_ascii=False, indent=2)
        utxo_serial = [
            {"txid": k[0], "index": k[1], "amount": v["amount"], "address": v["address"]}
            for k, v in self.utxos.items()
        ]
        with open(utxo_path, "w", encoding="utf-8") as f:
            json.dump(utxo_serial, f, ensure_ascii=False, indent=2)

    def load_from_file(self, chain_path: str, utxo_path: str):
        with open(chain_path, "r", encoding="utf-8") as f:
            chain_data = json.load(f)
        loaded = []
        for b in chain_data:
            block = Block(b["index"], b["transactions"], b["timestamp"], b["previous_hash"], b["nonce"])
            block.hash = b["hash"]
            loaded.append(block)
        self.chain = loaded

        with open(utxo_path, "r", encoding="utf-8") as f:
            utxo_serial = json.load(f)
        self.utxos = {}
        for item in utxo_serial:
            self.utxos[(item["txid"], int(item["index"]))] = {"amount": int(item["amount"]), "address": item["address"]}

