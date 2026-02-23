VENV = env

ifeq ($(OS),Windows_NT)
    BIN    = $(VENV)/Scripts
    RMVENV = rmdir /s /q $(VENV)
else
    BIN    = $(VENV)/bin
    RMVENV = rm -rf $(VENV)
endif

.PHONY: install run lint clean

install:
	python -m venv $(VENV)
	$(BIN)/pip install -r requirements.txt

run:
	$(BIN)/streamlit run healthkit_diabetes.py

lint:
	$(BIN)/pylint --ignore=$(VENV) .

clean:
	$(RMVENV)
