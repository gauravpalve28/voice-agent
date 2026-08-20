# ─── Stage 1: Build ───────────────────────────────────────────────────────────
FROM node:22-alpine AS builder

WORKDIR /app

# Install dependencies
COPY package*.json ./
RUN npm ci

# Copy source and build
COPY . .
RUN npm run build

# ─── Stage 2: Production (Nginx) ──────────────────────────────────────────────
FROM nginx:alpine AS production

# Copy built assets to Nginx's serve directory
COPY --from=builder /app/dist /usr/share/nginx/html

# Replace the default nginx config with our reverse-proxy config.
# This routes /api/* (REST + WebSocket) to the backend service on port 8000
# and serves the React SPA for all other paths.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port 80 (production static serving)
EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
