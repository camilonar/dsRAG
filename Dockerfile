# Use the official Python image
FROM python:3.12-slim

# Stablish the workdir for the Docker container
WORKDIR /app

# Copy the app files to the container
COPY . /app

# Install specific dependencies from requirements.txt
RUN pip install --no-cache-dir -r full_requirements.txt
RUN pip install voyageai

# Exposes the port where FastAPI will execute and listen for requests
EXPOSE 8000

# Command to execute the app when the container is deployed
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "asyncio"]
