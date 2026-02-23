VENV = env

ifeq ($(OS),Windows_NT)
    BIN    = $(VENV)/Scripts
    EXE    = .exe
    RMVENV = rmdir /s /q $(VENV)
else
    BIN    = $(VENV)/bin
    EXE    =
    RMVENV = rm -rf $(VENV)
endif

.PHONY: install run lint clean

install:
	python -m venv $(VENV)
	$(BIN)/pip$(EXE) install -r requirements.txt

run:
	$(BIN)/streamlit$(EXE) run healthkit_diabetes.py

lint:
	$(BIN)/pylint$(EXE) .

clean:
	$(RMVENV)
