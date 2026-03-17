FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Set Python path to include src directory
ENV PYTHONPATH=/app/src:$PYTHONPATH

# Ne futtassuk az init_db.py-t build időben, mert a DB még nem fut
# Helyette egy entrypoint script fogja kezelni

CMD ["python", "src/core/discord_bot.py"]
