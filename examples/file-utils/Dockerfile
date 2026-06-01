FROM python:3.11-slim

# Create non-root user for security
RUN useradd -m -u 1000 mcpuser

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY file_utils_server.py .

# Switch to non-root user
USER mcpuser

# Run the server
ENTRYPOINT ["python", "file_utils_server.py"]
