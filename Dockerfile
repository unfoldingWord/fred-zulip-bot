# Use Chainguard Wolfi base image
FROM cgr.dev/chainguard/wolfi-base

# Set Python version
ARG version=3.13

# Set working directory
WORKDIR /app

# Install Python and pip
RUN apk update && apk add --no-cache \
    python-${version} \
    py${version}-pip \
    py${version}-setuptools \
    git

# Change ownership of app directory to nonroot user
RUN chown -R nonroot:nonroot /app/

# Copy application code
COPY . .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Switch to non-root user
USER nonroot

# Expose FastAPI port
EXPOSE 8000

# Use entrypoint script to start the app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
