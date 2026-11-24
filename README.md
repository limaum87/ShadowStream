# ShadowStream - Raspberry Radio

Web UI para controlar reproducao de audio em um Raspberry Pi. O navegador e apenas um controle remoto — o som sai pela saida de audio do Raspberry.

Inclui suporte a **rádios online**, **playlists públicas do YouTube** (via mpv) e **Spotify Connect** (via raspotify/librespot).

## Requisitos

- Raspberry Pi com Raspbian/Raspberry Pi OS
- Python 3 (ja vem instalado)
- mpv
- raspotify (opcional, para Spotify Connect)

## Instalacao

### 1. Instalar dependencias

```bash
sudo apt-get update
sudo apt-get install -y mpv
```

### 2. Copiar arquivos

```bash
sudo mkdir -p /opt/radio
sudo cp app/* /opt/radio/
```

### 3. Criar servico systemd

```bash
sudo tee /etc/systemd/system/radio.service > /dev/null << 'EOF'
[Unit]
Description=Raspberry Radio
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/radio
ExecStart=/usr/bin/python3 /opt/radio/server.py
Restart=on-failure
RestartSec=5
Environment=PORT=10000
Environment=MPV_AUDIO_DEVICE=auto

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable radio.service
sudo systemctl start radio.service
```

### 4. Spotify Connect (opcional)

Para Raspberry Pi ARMv7+ (Pi 2, 3, 4, 5):

```bash
curl -sL https://dtcooper.github.io/raspotify/install.sh | sh
```

Para Raspberry Pi ARMv6 (Pi Zero, Pi 1) usar a ultima versao compativel:

```bash
curl -sL -o /tmp/raspotify.deb \
  'https://github.com/dtcooper/raspotify/releases/download/0.31.8.1/raspotify_0.31.8.1.librespot.v0.3.1-54-gf4be9bb_armhf.deb'
sudo dpkg -i /tmp/raspotify.deb
```

Configurar o nome do dispositivo:

```bash
sudo sed -i 's|#LIBRESPOT_NAME="Librespot"|LIBRESPOT_NAME="Raspberry Radio"|' /etc/raspotify/conf
sudo systemctl restart raspotify
```

Permitir que o servico radio controle o raspotify:

```bash
echo 'root ALL=(ALL) NOPASSWD: /usr/bin/systemctl start raspotify, /usr/bin/systemctl stop raspotify' \
  | sudo tee /etc/sudoers.d/radio-spotify
sudo chmod 440 /etc/sudoers.d/radio-spotify
```

## Uso

Abra `http://IP_DO_RASPBERRY:10000` de qualquer dispositivo na rede.

### Radio/Streams

- Selecione uma estacao e clique em **Tocar**
- Use **Pausar**, **Retomar** e **Parar** para controlar
- Ajuste o volume pelo slider
- Adicione ou remova estacoes direto pela interface web

### Spotify Connect

- Ative o toggle "Spotify Connect" na interface web
- Abra o Spotify no celular/PC
- Selecione **"Raspberry Radio"** como dispositivo de reproducao
- Controle a musica normalmente pelo app do Spotify

### Playlists do YouTube

Em **Adicionar rádio ou playlist**, informe um nome e cole o link da playlist pública do YouTube (`https://www.youtube.com/playlist?list=...`). Selecione-a e clique em **Tocar**. As faixas avançam automaticamente, e o áudio sai pelo Raspberry.

Para um Mix do YouTube, cole o link do vídeo aberto dentro do Mix. A rádio carrega até 20 faixas por Mix para limitar o tempo de espera no Raspberry.

A imagem Docker já inclui `yt-dlp` e QuickJS. Para uma instalação via `systemd`, use Python 3.11 ou mais recente para o `yt-dlp` e instale os componentes EJS. O executável `yt-dlp` deve estar no `PATH` do serviço. Por exemplo:

```bash
sudo apt-get install -y python3-venv
sudo python3 -m venv /opt/yt-dlp
sudo /opt/yt-dlp/bin/pip install -U yt-dlp yt-dlp-ejs
sudo ln -s /opt/yt-dlp/bin/yt-dlp /usr/local/bin/yt-dlp
```

Instale um [runtime JavaScript compatível com o `yt-dlp`](https://github.com/yt-dlp/yt-dlp/wiki/EJS#supported-javascript-runtimes). Com QuickJS instalado e `qjs` no `PATH` do serviço, adicione `--js-runtimes quickjs` a `/etc/yt-dlp.conf`. Com Deno, o `yt-dlp` detecta o executável por padrão. Depois de copiar os arquivos da aplicação, reinicie `radio.service`.

Com `mpv` 0.32, disponibilize também o executável como `youtube-dl` no `PATH` do serviço, pois essa versão procura o extrator por esse nome.

## Comandos uteis

```bash
sudo systemctl status radio        # status do servico
sudo systemctl restart radio       # reiniciar
sudo systemctl stop radio          # parar

sudo systemctl status raspotify    # status do Spotify Connect
sudo systemctl restart raspotify   # reiniciar Spotify Connect
```

## Alternativa: Docker

Tambem e possivel rodar via Docker (sem Spotify Connect):

```bash
docker compose up -d --build
```

## Notas

- No ARMv6 (Pi Zero/1), o mpv demora ~20s para iniciar. O timeout esta configurado para 30s.
- `MPV_AUDIO_DEVICE` pode ser configurado no servico caso precise de um dispositivo ALSA especifico.
- As estacoes ficam salvas em `/opt/radio/stations.json` e persistem entre reinicializacoes.
- Spotify Connect requer conta **Spotify Premium**.
