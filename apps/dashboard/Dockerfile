# Stage 1: Build the React Application
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
# --legacy-peer-deps: react-scripts@5 declares peer deps for React 17/18
# NODE_OPTIONS: webpack 4 (used by react-scripts 5) needs legacy OpenSSL on Node 20
RUN NODE_OPTIONS=--openssl-legacy-provider npm ci --legacy-peer-deps
COPY . .
RUN NODE_OPTIONS=--openssl-legacy-provider npm run build

# Stage 2: Serve the React Application using Nginx
FROM nginx:stable-alpine
COPY --from=builder /app/build /usr/share/nginx/html
# COPY custom nginx config to support SPA routing if needed
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
