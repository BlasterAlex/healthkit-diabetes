VENV = env

.PHONY: install run lint clean

install:
	python -m venv $(VENV)
	$(VENV)\Scripts\pip.exe install -r requirements.txt

run:
	$(VENV)\Scripts\streamlit.exe run healthkit_diabetes.py

lint:
	$(VENV)\Scripts\pylint.exe healthkit_diabetes.py

clean:
	rmdir /s /q $(VENV)
