def prepare(config):
    import nltk
    from nltk.tokenize import sent_tokenize

    root = config.nltk_dir or config.data_dir / "nltk"
    if str(root) not in nltk.data.path:
        nltk.data.path.insert(0, str(root))
    nltk.data.find("tokenizers/punkt_tab/english", paths=[str(root)])
    if len(sent_tokenize("Hola. Soy Gianna. Seguimos conversando.")) != 3:
        raise RuntimeError("Sentence tokenizer preflight failed")
