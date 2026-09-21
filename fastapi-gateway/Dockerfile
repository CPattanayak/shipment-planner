FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip

# Install pyautogen FIRST so pip resolves flaml/openai versions around it.
# Installing it last causes flaml[automl] to conflict with already-pinned deps.
RUN pip install --no-cache-dir "pyautogen==0.2.35"

# Install the rest; pip keeps versions already chosen above where compatible.
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
