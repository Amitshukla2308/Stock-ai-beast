FROM node:20-slim

WORKDIR /app

# Install dependencies
COPY package.json .
RUN npm install

# Copy source
COPY . .

# Expose port and start vite dev server
CMD ["npm", "run", "dev"]
