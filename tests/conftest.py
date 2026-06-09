"""
conftest.py
-----------
Configurazione pytest per la test suite di Data-Whisperer.

Mocka llama_cpp prima che qualsiasi modulo lo importi, in modo che
core_engine.py possa essere importato in CI senza installare llama-cpp-python
(che richiede compilazione C++).
"""
import sys
from unittest.mock import MagicMock

# Stub llama_cpp e llama_cpp.Llama prima di qualsiasi import
_llama_mock = MagicMock()
_llama_mock.Llama = MagicMock
sys.modules.setdefault("llama_cpp", _llama_mock)
