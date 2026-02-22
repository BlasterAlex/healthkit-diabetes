VENV = env
STREAMLIT = $(VENV)\Scripts\streamlit.exe
PIP = $(VENV)\Scripts\pip.exe

.PHONY: install run clean

install:
	python -m venv $(VENV)
	$(PIP) install -r requirements.txt

run:
	$(STREAMLIT) run healthkit_diabetes.py

clean:
	rmdir /s /q $(VENV)
