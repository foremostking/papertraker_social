# 使用已有的 node:latest 镜像
FROM node:latest

WORKDIR /app

# 复制 package 文件
COPY package*.json ./

# 安装依赖
RUN npm install

# 复制源代码
COPY . .

# 开发模式暴露端口
EXPOSE 5173

# 开发服务器启动命令
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
