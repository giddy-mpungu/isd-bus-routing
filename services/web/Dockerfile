# Build context is services/web itself (self-contained, unlike
# services/api's Dockerfile):
#   docker build -f services/web/Dockerfile -t isd-web services/web

FROM node:24-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Vite env vars are baked in at BUILD time, not read at container
# runtime — pass a non-default API origin via --build-arg, not a
# `docker run -e` at deploy time (that would silently do nothing).
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD wget -q --spider http://localhost/ || exit 1
