"""
Assignment 2 Python Blockchain Implementation.

- Block: index, timestamp, transactions, previous_hash, nonce, hash
- Transactions: UTXO-style inputs/outputs; txid = sha256 of canonical JSON
- Chain integrity: SHA-256, previous_hash linkage, PoW (configurable difficulty)
- Double-spend prevention: UTXO set (txid,index) -> {amount, address}
- Persistence: save/load chain, utxos and mempool to JSON
NOTE: No cryptographic signatures in this assignment; addresses are plain strings.
"""
from __future__ import annotations
import hashlib
import json
import time
import os
from typing import Any, Dict, List, Tuple, Optional


def sha256_json(obj: Any) -> str:
    """Return SHA256 hex of canonical JSON representation of obj."""
    s = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(s.encode()).hexdigest()


class Transaction:
    """
    UTXO-style transaction representation.
    inputs: list of {"txid": str, "index": int, "address": str}
    outputs: list of {"amount": int, "address": str}
    """
    def __init__(self, inputs: List[Dict[str, Any]], outputs: List[Dict[str, Any]]):
        self.inputs = inputs
        self.outputs = outputs
        self.txid = self.compute_txid()

    def compute_txid(self) -> str:
        content = {"inputs": self.inputs, "outputs": self.outputs}
        return sha256_json(content)

    def to_dict(self) -> Dict[str, Any]:
        return {"txid": self.txid, "inputs": self.inputs, "outputs": self.outputs}

    @staticmethod
    def coinbase(miner_address: str, amount: int, height: int) -> "Transaction":
        """Create a coinbase transaction (special input)."""
        outputs = [{"amount": amount, "address": miner_address}]
        # Use height in the 'input' to make coinbase unique
        tx = Transaction(inputs=[{"txid": "COINBASE", "index": height, "address": "COINBASE"}],
                         outputs=outputs)
        return tx


class Block:
    """Block structure holding transactions and PoW nonce/hash."""
    def __init__(self, index: int, transactions: List[Dict[str, Any]], timestamp: float,
                 previous_hash: str, nonce: int = 0, difficulty: int = 3):
        self.index = index
        self.transactions = transactions  # list of tx dicts
        self.timestamp = timestamp
        self.previous_hash = previous_hash
        self.nonce = nonce
        self.hash: Optional[str] = None
        self.difficulty = difficulty

    def compute_hash(self) -> str:
        content = {
            "index": self.index,
            "transactions": self.transactions,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
        }
        return sha256_json(content)

    def mine(self, difficulty: Optional[int] = None):
        """Simple Proof-of-Work loop: find nonce where hash starts with difficulty zeros."""
        target = "0" * (difficulty if difficulty is not None else self.difficulty)
        self.nonce = 0
        h = self.compute_hash()
        while not h.startswith(target):
            self.nonce += 1
            h = self.compute_hash()
        self.hash = h
        return h

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "transactions": self.transactions,
            "timestamp": self.timestamp,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "hash": self.hash,
            "difficulty": self.difficulty,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Block":
        return cls(
            index=data["index"],
            transactions=data.get("transactions", []),
            timestamp=data.get("timestamp", time.time()),
            previous_hash=data.get("previous_hash", "0"),
            nonce=data.get("nonce", 0),
            difficulty=data.get("difficulty", 3)
        )


class Blockchain:
    """
    Minimal blockchain with:
    - chain: list of Block
    - unconfirmed_transactions: mempool (list of tx dicts)
    - utxos: dict[(txid, index)] -> {"amount": int, "address": str}
    """
    def __init__(self, data_dir: str = os.path.join(os.path.dirname(__file__), "..", "data"),
                 difficulty: int = 3, block_reward: int = 50):
        self.chain: List[Block] = []
        self.unconfirmed_transactions: List[Dict[str, Any]] = []
        self.utxos: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self.difficulty = difficulty
        self.block_reward = block_reward

        # persistence paths
        os.makedirs(data_dir, exist_ok=True)
        self.chain_path = os.path.join(data_dir, "chain.json")
        self.utxo_path = os.path.join(data_dir, "utxos.json")
        self.mempool_path = os.path.join(data_dir, "mempool.json")

        # If no files, create a genesis block automatically
        if not (os.path.exists(self.chain_path) and os.path.exists(self.utxo_path)):
            self.create_genesis_block()
            self.save_to_file()
        else:
            # if files exist, try to load
            try:
                self.load_from_file()
            except Exception:
                # fallback: create genesis
                self.chain = []
                self.utxos = {}
                self.unconfirmed_transactions = []
                self.create_genesis_block()
                self.save_to_file()

    # ------------------ UTXO helpers ------------------

    def _clone_utxo(self) -> Dict[Tuple[str, int], Dict[str, Any]]:
        return {k: v.copy() for k, v in self.utxos.items()}

    def _validate_and_apply_to_utxo(self, tx: Transaction, utxo_view: Dict[Tuple[str, int], Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
        """
        Validate a Transaction against a provided utxo_view (dictionary).
        If valid, apply changes to utxo_view (consume inputs, add outputs).
        """
        # coinbase cannot be in mempool
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

        # apply: remove inputs, add outputs
        for i in tx.inputs:
            key = (i["txid"], int(i["index"]))
            utxo_view.pop(key, None)
        for idx, o in enumerate(tx.outputs):
            utxo_view[(tx.txid, idx)] = {"amount": int(o["amount"]), "address": o["address"]}
        return True, None

    # ------------------ Chain / mempool operations ------------------

    def create_genesis_block(self, miner_address: str = "alice"):
        """Create a genesis block that gives block_reward to miner_address and initializes UTXO set."""
        coinbase = Transaction.coinbase(miner_address, self.block_reward, height=0)
        genesis_block = Block(
            index=0,
            transactions=[coinbase.to_dict()],
            timestamp=time.time(),
            previous_hash="0",
            nonce=0,
            difficulty=self.difficulty
        )
        genesis_block.mine(self.difficulty)
        self.chain = [genesis_block]
        # set utxos from coinbase
        self.utxos = {}
        for idx, o in enumerate(coinbase.outputs):
            self.utxos[(coinbase.txid, idx)] = {"amount": int(o["amount"]), "address": o["address"]}

    def add_new_transaction(self, tx: Dict[str, Any]) -> bool:
        """
        Add transaction to mempool if it validates against current utxos + pending mempool effects.
        Prevents double-spending with mempool.
        """
        try:
            tx_obj = Transaction(inputs=tx["inputs"], outputs=tx["outputs"])
            if "txid" in tx and tx["txid"] != tx_obj.txid:
                return False
        except Exception:
            return False

        # create temp view and apply existing mempool txs to it
        temp_utxo = self._clone_utxo()
        for pending in self.unconfirmed_transactions:
            pending_tx = Transaction(pending["inputs"], pending["outputs"])
            ok, _ = self._validate_and_apply_to_utxo(pending_tx, temp_utxo)
            if not ok:
                # If a pending tx is invalid against current utxo, skip (shouldn't normally happen)
                pass

        ok, err = self._validate_and_apply_to_utxo(tx_obj, temp_utxo)
        if not ok:
            return False

        # all good -> append to mempool and persist
        self.unconfirmed_transactions.append(tx_obj.to_dict())
        self.save_to_file()
        return True

    def mine(self, miner_address: str) -> int:
        """
        Build a new block with a coinbase tx + as many valid mempool txs as possible.
        Update utxos and append block to chain.
        """
        # coinbase (height = next index)
        coinbase_tx = Transaction.coinbase(miner_address, self.block_reward, height=len(self.chain))
        txs_to_include: List[Dict[str, Any]] = [coinbase_tx.to_dict()]

        # use temp utxo applying coinbase first so mempool txs validated against that view
        temp_utxo = self._clone_utxo()
        # add coinbase outputs to temp_utxo
        for idx, o in enumerate(coinbase_tx.outputs):
            temp_utxo[(coinbase_tx.txid, idx)] = {"amount": int(o["amount"]), "address": o["address"]}

        included = []
        for txd in self.unconfirmed_transactions:
            tx_obj = Transaction(txd["inputs"], txd["outputs"])
            ok, _ = self._validate_and_apply_to_utxo(tx_obj, temp_utxo)
            if ok:
                included.append(txd)

        txs_to_include.extend(included)

        last_hash = self.chain[-1].hash if self.chain else "0"
        new_block = Block(
            index=len(self.chain),
            transactions=txs_to_include,
            timestamp=time.time(),
            previous_hash=last_hash,
            nonce=0,
            difficulty=self.difficulty
        )

        # mine PoW
        new_block.mine(self.difficulty)

        # append block & commit temp_utxo to real utxos
        self.chain.append(new_block)
        self.utxos = temp_utxo

        # remove included txs from mempool and persist
        self.unconfirmed_transactions = [t for t in self.unconfirmed_transactions if t not in included]
        self.save_to_file()

        return new_block.index

    # ------------------ Validation & persistence ------------------

    def is_chain_valid(self) -> bool:
        temp_utxo: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for i, b in enumerate(self.chain):
            if i == 0:
                # genesis checks
                if b.previous_hash != "0":
                    return False
                if b.compute_hash() != b.hash:
                    return False
                # build utxo from genesis coinbase
                if b.transactions:
                    coinbase = Transaction(b.transactions[0]["inputs"], b.transactions[0]["outputs"])
                    for idx, o in enumerate(coinbase.outputs):
                        temp_utxo[(coinbase.txid, idx)] = {"amount": int(o["amount"]), "address": o["address"]}
                continue
            prev = self.chain[i - 1]
            if b.previous_hash != prev.hash:
                return False
            if b.compute_hash() != b.hash:
                return False
            if not b.hash.startswith("0" * self.difficulty):
                return False
            # apply transactions
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

    def save_to_file(self):
        """Persist chain, utxos and mempool to disk (JSON)."""
        # chain
        with open(self.chain_path, "w", encoding="utf-8") as f:
            json.dump([b.to_dict() for b in self.chain], f, ensure_ascii=False, indent=2)

        # utxos as a list of records
        utxo_serial = [
            {"txid": k[0], "index": k[1], "amount": v["amount"], "address": v["address"]}
            for k, v in self.utxos.items()
        ]
        with open(self.utxo_path, "w", encoding="utf-8") as f:
            json.dump(utxo_serial, f, ensure_ascii=False, indent=2)

        # mempool
        with open(self.mempool_path, "w", encoding="utf-8") as f:
            json.dump(self.unconfirmed_transactions, f, ensure_ascii=False, indent=2)

    def load_from_file(self):
        """Load chain, utxos and mempool from disk. If files missing, do nothing."""
        # chain
        if os.path.exists(self.chain_path):
            with open(self.chain_path, "r", encoding="utf-8") as f:
                chain_data = json.load(f)
            self.chain = [Block.from_dict(b) for b in chain_data]
        # utxos
        if os.path.exists(self.utxo_path):
            with open(self.utxo_path, "r", encoding="utf-8") as f:
                utxo_serial = json.load(f)
            self.utxos = {}
            # utxo_serial expected to be list of {"txid":..., "index":..., "amount":..., "address":...}
            if isinstance(utxo_serial, list):
                for item in utxo_serial:
                    self.utxos[(item["txid"], int(item["index"]))] = {"amount": int(item["amount"]), "address": item["address"]}
        # mempool
        if os.path.exists(self.mempool_path):
            with open(self.mempool_path, "r", encoding="utf-8") as f:
                self.unconfirmed_transactions = json.load(f)

