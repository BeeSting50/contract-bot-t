FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY bot.py .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash app
USER app

# Run the bot
CMD ["python3", "bot.py"]