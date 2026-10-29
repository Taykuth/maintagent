# Hugging Face Spaces (Docker) için. Space'e sadece bu dosya ve yanındaki README.md yüklenir;
# kod derleme sırasında GitHub'dan alınır.
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends git libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Spaces konteyneri 1000 numaralı kullanıcıyla çalıştırır
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1 PORT=7860
WORKDIR /home/user/app

ARG REPO=https://github.com/Taykuth/maintagent.git
ARG BRANCH=main
# Commit akışı her yeni commit'te değişir; Docker önbelleği bozulur ve kod yeniden alınır.
# (GitHub API yerine akış: API'nin istek sınırı paylaşılan derleme sunucularında dolabiliyor.)
ADD https://github.com/Taykuth/maintagent/commits/main.atom /tmp/last_commits.atom
RUN git clone --depth 1 --branch $BRANCH $REPO .

# torch'un sadece CPU sürümü: CUDA'lı sürüm birkaç GB daha büyük
RUN pip install --no-cache-dir --user torch --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir --user -r requirements.txt -r requirements-embed.txt kaggle

# Embedding modeli imaja gömülür; açılışta indirilmez
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-small')"

EXPOSE 7860
CMD ["bash", "deploy/start.sh"]
