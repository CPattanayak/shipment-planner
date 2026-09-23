FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .

RUN pip install --upgrade pip

# autogen-agentchat 0.4.x replaces pyautogen 0.2.x.
# No pre-install workaround needed — flaml conflict was pyautogen-specific.
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

COPY . .

EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
