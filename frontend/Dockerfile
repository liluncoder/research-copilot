# 构建阶段
FROM node:20-alpine AS builder
WORKDIR /app

# ★同上：默认走 npmmirror。直连 npmjs 在国内实测 17 分钟级。
#   海外构建 / 镜像不可用时切回官方源：
#     docker compose build --build-arg NPM_REGISTRY=https://registry.npmjs.org
ARG NPM_REGISTRY=https://registry.npmmirror.com

COPY package.json package-lock.json ./
# ★只设 registry 还不够：package-lock.json 里记着 registry.npmjs.org 的绝对地址，
#   npm 会照着 lock 里的 resolved 去下，镜像设置就白设了。所以把 host 一起替换掉。
#   （只在镜像内改，不动仓库里的源文件。）
RUN npm config set registry "${NPM_REGISTRY}" \
 && npm config set fetch-retries 5 \
 && sed -i "s|https://registry.npmjs.org|${NPM_REGISTRY}|g" package-lock.json \
 && npm install --no-audit --no-fund
COPY . .
RUN npm run build

# 运行阶段（standalone 输出）
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
