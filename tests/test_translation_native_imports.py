from __future__ import annotations

import pytest


@pytest.mark.translation_native
def test_pinned_native_translation_packages_import() -> None:
    import argostranslate.translate
    import ctranslate2
    import llama_cpp
    import sentencepiece
    from llama_cpp import llama_cpp as llama_native

    assert callable(argostranslate.translate.get_installed_languages)
    assert hasattr(llama_cpp, "Llama")
    assert ctranslate2.__version__
    assert sentencepiece.SentencePieceProcessor is not None
    assert llama_native._lib is not None
