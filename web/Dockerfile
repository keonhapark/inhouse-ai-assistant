# 빌드: Node로 정적 파일을 만들고, 실행: nginx가 정적 파일과 /api 프록시를 맡습니다.
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.29-alpine
ENV GATEWAY_URL=http://gateway:8000
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD wget -q -O /dev/null http://127.0.0.1/health || exit 1
