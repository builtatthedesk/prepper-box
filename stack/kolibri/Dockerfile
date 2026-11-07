# Kolibri (Learning Equality) baked into the image, so it starts with no internet.
FROM python:3.12-slim
ARG KOLIBRI_VERSION=0.19.5
RUN pip install --no-cache-dir "kolibri==${KOLIBRI_VERSION}" \
 && useradd -u 1000 -m kolibri
ENV KOLIBRI_HOME=/data PYTHONUNBUFFERED=1
USER 1000
EXPOSE 8080
CMD ["kolibri", "start", "--foreground", "--port=8080"]
