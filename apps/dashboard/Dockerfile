# Stage 1: Build the React Application
FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

# Stage 2: Serve the React Application using Nginx
FROM nginx:stable-alpine
COPY --from=builder /app/build /usr/share/nginx/html
# COPY custom nginx config to support SPA routing if needed
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
