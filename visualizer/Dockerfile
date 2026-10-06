FROM node:22.23.3-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE_URL
ARG VITE_APP_NAME="Tickets activos · IDL"
ARG VITE_TIMEZONE=America/Montevideo
ARG VITE_REFRESH_INTERVAL_MS=5000
ARG VITE_PAGE_INTERVAL_MS=15000
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} VITE_APP_NAME=${VITE_APP_NAME} VITE_TIMEZONE=${VITE_TIMEZONE} VITE_REFRESH_INTERVAL_MS=${VITE_REFRESH_INTERVAL_MS} VITE_PAGE_INTERVAL_MS=${VITE_PAGE_INTERVAL_MS}
RUN npm run build
FROM nginx:1.28.0-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 CMD wget -q --spider http://127.0.0.1/healthz || exit 1
