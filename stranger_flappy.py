#!/usr/bin/env python3
"""
STRANGER FLAPPY  -  Flappy Bird do Mundo Invertido controlado pela mão

Um sensor ultrassônico HC-SR04 ligado ao Arduino mede a distância da sua mão.
Quanto mais alta a mão, mais alto a Eleven voa. Desvie das vinhas do Mundo
Invertido (com bocas de Demogorgon).

Uso:
    pip install pygame pyserial
    python stranger_flappy.py                  # detecta o Arduino sozinho
    python stranger_flappy.py --port COM3      # Windows
    python stranger_flappy.py --port /dev/ttyACM0
    python stranger_flappy.py --sim            # sem Arduino (mouse controla)

Teclas:  ESPAÇO / clique = iniciar ou recomeçar | M = alterna mouse/sensor | ESC = sair
"""
import argparse
import array
import json
import math
import os
import random
import sys
import threading
import time

import pygame

try:
    import serial
    import serial.tools.list_ports
except ImportError:  # permite rodar em modo simulação sem pyserial
    serial = None

# --------------------------------------------------------------------------- #
# Configurações
# --------------------------------------------------------------------------- #
W, H = 960, 600
FPS = 60
TOP_MARGIN = 70          # faixa das luzes de Natal
GROUND_H = 70
PLAY_TOP = TOP_MARGIN
PLAY_BOTTOM = H - GROUND_H

# Faixa de distância da mão (cm) mapeada para a altura da Eleven
DIST_MIN = 6.0           # mão perto do sensor  -> Eleven embaixo
DIST_MAX = 36.0          # mão longe do sensor  -> Eleven em cima
DIST_LOST = 60.0         # acima disso consideramos "sem mão"
SENSOR_TIMEOUT = 0.5     # s sem dados = sensor perdido

BIRD_X = 220
BIRD_R = 17              # raio de colisão (um pouco menor que o desenho)
PIPE_W = 84
PIPE_SPACING = 360
GAP_START = 215
GAP_MIN = 170
BASE_SPEED = 3.3         # px por frame a 60 fps
MAX_MULT = 2.5

BEST_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "best.json")

# Cores
BLOOD = (200, 20, 35)
DEEP_RED = (90, 8, 18)
VINE_DARK = (38, 8, 16)
VINE_MID = (82, 14, 26)
VINE_LIGHT = (150, 36, 46)
BONE = (230, 215, 190)
XMAS = [(255, 60, 60), (255, 210, 60), (70, 200, 255), (90, 255, 120), (255, 120, 220)]


# --------------------------------------------------------------------------- #
# Sensor (Arduino pela serial)
# --------------------------------------------------------------------------- #
class Sensor:
    def __init__(self, port=None, baud=115200):
        self.port = port
        self.baud = baud
        self.ser = None
        self.dist = None
        self.stamp = 0.0
        self.running = False
        self.error = None

    @staticmethod
    def find_port():
        if serial is None:
            return None
        keys = ("arduino", "ch340", "usb serial", "usb-serial", "wch", "cp210", "ftdi", "acm", "usbserial")
        ports = list(serial.tools.list_ports.comports())
        for p in ports:
            text = f"{p.device} {p.description} {p.manufacturer or ''}".lower()
            if any(k in text for k in keys):
                return p.device
        return ports[0].device if ports else None

    def start(self):
        if serial is None:
            self.error = "pyserial não instalado (pip install pyserial)"
            return False
        port = self.port or self.find_port()
        if not port:
            self.error = "nenhuma porta serial encontrada"
            return False
        try:
            self.ser = serial.Serial(port, self.baud, timeout=0.2)
        except Exception as e:  # noqa: BLE001
            self.error = f"não abriu {port}: {e}"
            return False
        self.port = port
        time.sleep(2.0)  # o Arduino reinicia ao abrir a serial
        self.ser.reset_input_buffer()
        self.running = True
        threading.Thread(target=self._loop, daemon=True).start()
        return True

    def _loop(self):
        while self.running:
            try:
                line = self.ser.readline().decode("ascii", errors="ignore").strip()
            except Exception:  # noqa: BLE001
                self.error = "conexão perdida"
                self.dist = None
                time.sleep(0.5)
                continue
            if line.startswith("D:"):
                try:
                    v = float(line[2:])
                except ValueError:
                    continue
                self.dist = v if v >= 0 else None
                self.stamp = time.time()

    def read(self):
        """Distância em cm, ou None se não há leitura válida e recente."""
        if time.time() - self.stamp > SENSOR_TIMEOUT:
            return None
        return self.dist

    def send(self, cmd):
        if self.ser and self.running:
            try:
                self.ser.write(cmd.encode("ascii"))
            except Exception:  # noqa: BLE001
                pass

    def close(self):
        self.running = False
        if self.ser:
            try:
                self.ser.close()
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------- #
# Áudio sintetizado (sem arquivos externos)
# --------------------------------------------------------------------------- #
def make_tone(freq_start, freq_end, ms, volume=0.35, wobble=0.0):
    rate = 22050
    n = int(rate * ms / 1000)
    buf = array.array("h")
    phase = 0.0
    for i in range(n):
        t = i / n
        f = freq_start + (freq_end - freq_start) * t
        if wobble:
            f += math.sin(i * 0.01) * wobble
        phase += 2 * math.pi * f / rate
        env = min(1.0, (1 - t) * 3)
        s = math.sin(phase) + 0.4 * math.sin(2 * phase)
        buf.append(int(max(-1, min(1, s * 0.6)) * env * volume * 32767))
    return pygame.mixer.Sound(buffer=buf.tobytes())


class Audio:
    def __init__(self):
        self.ok = False
        try:
            pygame.mixer.init(frequency=22050, size=-16, channels=1, buffer=512)
            self.point = make_tone(660, 990, 130)
            self.dead = make_tone(220, 40, 800, volume=0.5, wobble=30)
            self.start = make_tone(110, 330, 400, volume=0.3)
            self.ok = True
        except Exception:  # noqa: BLE001
            pass

    def play(self, name):
        if self.ok:
            getattr(self, name).play()


# --------------------------------------------------------------------------- #
# Helpers de desenho
# --------------------------------------------------------------------------- #
def vertical_gradient(w, h, top, bottom):
    surf = pygame.Surface((w, h))
    for y in range(h):
        t = y / (h - 1)
        c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
        pygame.draw.line(surf, c, (0, y), (w, y))
    return surf


def glow_text(surf, text, font, center, color=BLOOD, glow=(120, 0, 15), spread=4):
    core = font.render(text, True, color)
    halo = font.render(text, True, glow)
    r = core.get_rect(center=center)
    for dist, alpha in ((spread * 2, 40), (spread, 90)):
        halo.set_alpha(alpha)
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (1, 1), (-1, 1), (1, -1)):
            surf.blit(halo, (r.x + dx * dist, r.y + dy * dist))
    surf.blit(core, r)


def build_trees(seed=7):
    """Silhueta de árvores mortas, em uma faixa larga que rola em paralaxe."""
    rnd = random.Random(seed)
    surf = pygame.Surface((W, H), pygame.SRCALPHA)
    x = 0
    while x < W:
        base_y = PLAY_BOTTOM
        h = rnd.randint(140, 300)
        trunk_w = rnd.randint(10, 20)
        pygame.draw.polygon(surf, (22, 6, 14, 255), [
            (x - trunk_w, base_y), (x - trunk_w // 3, base_y - h),
            (x + trunk_w // 3, base_y - h), (x + trunk_w, base_y)])
        for _ in range(rnd.randint(4, 7)):  # galhos
            by = base_y - rnd.randint(int(h * 0.3), h)
            side = rnd.choice((-1, 1))
            ln = rnd.randint(30, 90)
            ex, ey = x + side * ln, by - rnd.randint(20, 60)
            pygame.draw.line(surf, (22, 6, 14, 255), (x, by), (ex, ey), rnd.randint(3, 6))
            pygame.draw.line(surf, (22, 6, 14, 255), (ex, ey),
                             (ex + side * rnd.randint(10, 30), ey - rnd.randint(10, 30)), 2)
        x += rnd.randint(70, 150)
    return surf


# --------------------------------------------------------------------------- #
# Elementos do jogo
# --------------------------------------------------------------------------- #
class Pipe:
    def __init__(self, x, gap_y, gap):
        self.x = x
        self.gap_y = gap_y      # centro do vão
        self.gap = gap
        self.scored = False
        self.seed = random.random() * 100

    @property
    def top_end(self):
        return self.gap_y - self.gap / 2

    @property
    def bottom_start(self):
        return self.gap_y + self.gap / 2

    def hits(self, bx, by, r):
        # círculo x retângulo
        for (y0, y1) in ((0, self.top_end), (self.bottom_start, H)):
            cx = max(self.x, min(bx, self.x + PIPE_W))
            cy = max(y0, min(by, y1))
            if (bx - cx) ** 2 + (by - cy) ** 2 < r * r:
                return True
        return False

    def draw(self, surf, t):
        self._vine(surf, 0, self.top_end, t, from_top=True)
        self._vine(surf, self.bottom_start, H - GROUND_H + 10, t, from_top=False)

    def _vine(self, surf, y0, y1, t, from_top):
        if y1 - y0 < 4:
            return
        x, w, s = self.x, PIPE_W, self.seed
        left, right = [], []
        step = 10
        y = y0
        while y <= y1 + step:
            yy = min(y, y1)
            left.append((x + 5 * math.sin(yy * 0.045 + s + t * 0.8), yy))
            right.append((x + w - 5 * math.sin(yy * 0.06 + s * 2 + t * 0.7), yy))
            y += step
        pygame.draw.polygon(surf, VINE_MID, left + right[::-1])
        # veias
        for k in (0.22, 0.5, 0.78):
            pts = []
            for (lx, ly), (rx, _) in zip(left, right):
                pts.append((lx + (rx - lx) * k + 3 * math.sin(ly * 0.09 + s + k * 9), ly))
            if len(pts) > 1:
                pygame.draw.lines(surf, VINE_LIGHT if k == 0.5 else VINE_DARK, False, pts, 3)
        pygame.draw.lines(surf, VINE_DARK, False, left, 3)
        pygame.draw.lines(surf, VINE_DARK, False, right, 3)

        # tentáculos laterais
        rnd = random.Random(int(s * 1000) + (1 if from_top else 2))
        for _ in range(4):
            ty = rnd.uniform(y0 + 20, y1 - 20)
            side = rnd.choice((-1, 1))
            bx = x if side < 0 else x + w
            pts = []
            for i in range(8):
                px = bx + side * i * 6
                py = ty + math.sin(i * 0.8 + t * 2 + ty) * (i * 1.6)
                pts.append((px, py))
            pygame.draw.lines(surf, VINE_LIGHT, False, pts, 3)

        # boca de Demogorgon na ponta do vão
        cap_y = y1 if from_top else y0
        cx = x + w / 2
        pygame.draw.ellipse(surf, DEEP_RED, (cx - w / 2 - 12, cap_y - 20, w + 24, 40))
        pygame.draw.ellipse(surf, VINE_DARK, (cx - w / 2 - 12, cap_y - 20, w + 24, 40), 3)
        direction = 1 if from_top else -1
        n = 7
        open_amt = 2 + 2 * math.sin(t * 4 + s)
        for i in range(n):
            tx = cx - w / 2 - 4 + i * ((w + 8) / (n - 1))
            base = cap_y - direction * 2
            pygame.draw.polygon(surf, BONE, [
                (tx - 5, base), (tx + 5, base), (tx, base + direction * (14 + open_amt))])


class Spore:
    def __init__(self, scattered=True):
        self.reset(scattered)

    def reset(self, scattered=False):
        self.x = random.uniform(0, W)
        self.y = random.uniform(0, H) if scattered else H + 5
        self.vy = random.uniform(0.2, 0.9)
        self.r = random.choice((1, 1, 2, 2, 3))
        self.ph = random.uniform(0, 6.28)
        g = random.randint(150, 235)
        self.c = (g, int(g * 0.8), int(g * 0.7))

    def update(self, speed):
        self.y -= self.vy
        self.x += math.sin(time.time() + self.ph) * 0.3 - speed * 0.15
        if self.y < -5 or self.x < -5:
            self.reset()


# --------------------------------------------------------------------------- #
# Jogo
# --------------------------------------------------------------------------- #
class Game:
    def __init__(self, sensor, sim):
        pygame.init()
        pygame.display.set_caption("STRANGER FLAPPY - Mundo Invertido")
        self.screen = pygame.display.set_mode((W, H))
        self.clock = pygame.time.Clock()
        self.sensor = sensor
        self.sim = sim
        self.audio = Audio()

        fam = "georgia,timesnewroman,palatino,serif"
        self.f_title = pygame.font.SysFont(fam, 64, bold=True)
        self.f_big = pygame.font.SysFont(fam, 72, bold=True)
        self.f_mid = pygame.font.SysFont(fam, 34, bold=True)
        self.f_small = pygame.font.SysFont("arial,sans", 18)
        self.f_tiny = pygame.font.SysFont("arial,sans", 14)

        self.bg = vertical_gradient(W, H, (6, 8, 22), (92, 12, 28))
        self.trees = build_trees()
        self.tree_x = 0.0
        self.spores = [Spore() for _ in range(70)]
        self.flash = 0.0
        self.next_bolt = time.time() + random.uniform(2, 5)
        self.bolt = None
        self.shake = 0.0

        self.best = self._load_best()
        self.state = "WAIT"
        self.reset()

    # -- persistência
    def _load_best(self):
        try:
            with open(BEST_FILE) as f:
                return int(json.load(f).get("best", 0))
        except Exception:  # noqa: BLE001
            return 0

    def _save_best(self):
        try:
            with open(BEST_FILE, "w") as f:
                json.dump({"best": self.best}, f)
        except Exception:  # noqa: BLE001
            pass

    # -- controle
    def reset(self):
        self.score = 0
        self.pipes = []
        self.bird_y = (PLAY_TOP + PLAY_BOTTOM) / 2
        self.last_gap_y = self.bird_y
        self.dead_t = 0.0
        self.t = 0.0
        self.new_record = False

    @property
    def speed_mult(self):
        return min(1.0 + 0.014 * self.score, MAX_MULT)

    @property
    def gap(self):
        return max(GAP_MIN, GAP_START - self.score * 0.9)

    def target_y(self):
        """Altura desejada para a Eleven a partir da mão (ou do mouse)."""
        lo = PLAY_TOP + BIRD_R + 4
        hi = PLAY_BOTTOM - BIRD_R - 4
        if self.sim:
            my = pygame.mouse.get_pos()[1]
            return max(lo, min(hi, my))
        d = self.sensor.read() if self.sensor else None
        if d is None or d > DIST_LOST:
            return hi  # sem mão = Eleven cai
        d = max(DIST_MIN, min(DIST_MAX, d))
        norm = (d - DIST_MIN) / (DIST_MAX - DIST_MIN)
        return hi - norm * (hi - lo)

    def start(self):
        self.reset()
        self.state = "PLAY"
        self.audio.play("start")
        if self.sensor:
            self.sensor.send("R")

    def die(self):
        self.state = "OVER"
        self.shake = 14
        self.flash = 1.0
        self.audio.play("dead")
        if self.sensor:
            self.sensor.send("X")
        if self.score > self.best:
            self.best = self.score
            self.new_record = True
            self._save_best()

    # -- lógica
    def spawn_pipe(self):
        gap = self.gap
        margin = gap / 2 + PLAY_TOP + 25
        lo, hi = margin, PLAY_BOTTOM - gap / 2 - 25
        y = random.uniform(max(lo, self.last_gap_y - 170), min(hi, self.last_gap_y + 170))
        self.last_gap_y = y
        self.pipes.append(Pipe(W + 40, y, gap))

    def update(self, dt):
        k = dt * 60.0
        speed = BASE_SPEED * self.speed_mult * (1.0 if self.state == "PLAY" else 0.0)
        self.tree_x = (self.tree_x + speed * 0.25 * k) % W
        for s in self.spores:
            s.update(speed)

        # relâmpagos
        now = time.time()
        if now > self.next_bolt:
            self.flash = 0.75
            self.bolt = self._make_bolt()
            self.next_bolt = now + random.uniform(3, 8)
        self.flash = max(0.0, self.flash - 0.04 * k)
        if self.flash <= 0:
            self.bolt = None
        self.shake = max(0.0, self.shake - 0.8 * k)

        # Eleven segue a mão com suavização
        if self.state != "OVER":
            self.bird_y += (self.target_y() - self.bird_y) * min(1.0, 0.22 * k)
        else:
            self.dead_t += dt
            self.bird_y = min(PLAY_BOTTOM - 10, self.bird_y + 5 * k)

        if self.state != "PLAY":
            return

        self.t += dt
        if not self.pipes or self.pipes[-1].x < W - PIPE_SPACING:
            self.spawn_pipe()

        for p in self.pipes:
            p.x -= speed * k
            if not p.scored and p.x + PIPE_W < BIRD_X - BIRD_R:
                p.scored = True
                self.score += 1
                self.audio.play("point")
                if self.sensor:
                    self.sensor.send("S")
            if p.hits(BIRD_X, self.bird_y, BIRD_R):
                self.die()
                break
        self.pipes = [p for p in self.pipes if p.x > -PIPE_W - 40]

    def _make_bolt(self):
        x = random.randint(80, W - 80)
        pts = [(x, 0)]
        y = 0
        while y < PLAY_BOTTOM - 150:
            y += random.randint(25, 55)
            x += random.randint(-30, 30)
            pts.append((x, y))
        return pts

    # -- desenho
    def draw_lights(self, t):
        """Fio de luzes de Natal no topo (a 'parede da Joyce')."""
        pts = []
        n = 22
        for i in range(n + 1):
            x = i * W / n
            y = 18 + 14 * math.sin(i / n * math.pi * 4) ** 2
            pts.append((x, y))
        pygame.draw.lines(self.screen, (10, 10, 10), False, pts, 3)
        for i, (x, y) in enumerate(pts):
            c = XMAS[i % len(XMAS)]
            flick = 0.55 + 0.45 * math.sin(t * 7 + i * 1.9) * math.sin(t * 3.1 + i)
            if random.random() < 0.01:
                flick = 0.1
            col = tuple(int(v * max(0.15, flick)) for v in c)
            pygame.draw.circle(self.screen, tuple(v // 4 for v in col), (int(x), int(y) + 10), 11)
            pygame.draw.circle(self.screen, col, (int(x), int(y) + 10), 6)

    def draw_eleven(self, surf, x, y, t, dead=False):
        y = int(y)
        # aura de telecinese
        if not dead:
            pulse = 26 + 3 * math.sin(t * 8)
            aura = pygame.Surface((90, 90), pygame.SRCALPHA)
            pygame.draw.circle(aura, (90, 170, 255, 45), (45, 45), int(pulse + 8))
            pygame.draw.circle(aura, (140, 210, 255, 70), (45, 45), int(pulse))
            surf.blit(aura, (x - 45, y - 45))
        skin = (238, 200, 172)
        hair = (96, 64, 42)
        pink = (226, 140, 170)
        # vestido
        pygame.draw.polygon(surf, pink, [(x - 11, y + 12), (x + 11, y + 12), (x + 17, y + 34), (x - 17, y + 34)])
        # cabelo (corte curto) atrás
        pygame.draw.ellipse(surf, hair, (x - 22, y - 24, 44, 40))
        # rosto
        pygame.draw.circle(surf, skin, (x, y), 17)
        # franja
        pygame.draw.polygon(surf, hair, [(x - 19, y - 8), (x - 14, y - 22), (x + 14, y - 22), (x + 19, y - 8),
                                         (x + 8, y - 12), (x, y - 8), (x - 8, y - 13)])
        # olhos
        if dead:
            for ex in (x - 7, x + 7):
                pygame.draw.line(surf, (30, 20, 20), (ex - 3, y - 3), (ex + 3, y + 3), 2)
                pygame.draw.line(surf, (30, 20, 20), (ex - 3, y + 3), (ex + 3, y - 3), 2)
        else:
            for ex in (x - 7, x + 7):
                pygame.draw.circle(surf, (255, 255, 255), (ex, y - 1), 4)
                pygame.draw.circle(surf, (30, 20, 20), (ex + 1, y - 1), 2)
        # boca
        pygame.draw.line(surf, (150, 70, 70), (x - 4, y + 9), (x + 4, y + 9), 2)
        # sangramento do nariz (marca registrada)
        nose = 8 + (min(40, self.dead_t * 60) if dead else 0)
        pygame.draw.line(surf, (190, 15, 25), (x + 1, y + 4), (x + 1, y + 4 + nose * 0.5), 3)

    def draw_world(self, surf):
        surf.blit(self.bg, (0, 0))
        # brilho vermelho no horizonte
        glow = pygame.Surface((W, 160), pygame.SRCALPHA)
        for i in range(160):
            pygame.draw.line(glow, (200, 30, 40, int(70 * i / 160)), (0, i), (W, i))
        surf.blit(glow, (0, PLAY_BOTTOM - 160))
        # árvores com paralaxe
        ox = -int(self.tree_x)
        surf.blit(self.trees, (ox, 0))
        surf.blit(self.trees, (ox + W, 0))
        # raio
        if self.bolt:
            pygame.draw.lines(surf, (255, 230, 230), False, self.bolt, 3)
            pygame.draw.lines(surf, (255, 90, 90), False, self.bolt, 1)
        # esporos
        for s in self.spores:
            pygame.draw.circle(surf, s.c, (int(s.x), int(s.y)), s.r)
        # canos
        for p in self.pipes:
            p.draw(surf, time.time())
        # chão: terra orgânica com veias
        pygame.draw.rect(surf, (28, 6, 14), (0, PLAY_BOTTOM, W, GROUND_H))
        for i in range(0, W, 24):
            off = (i - int(self.tree_x * 4)) % W
            pygame.draw.line(surf, VINE_MID, (off, PLAY_BOTTOM), (off - 14, PLAY_BOTTOM + GROUND_H), 3)
        pygame.draw.line(surf, VINE_LIGHT, (0, PLAY_BOTTOM), (W, PLAY_BOTTOM), 4)
        self.draw_eleven(surf, BIRD_X, self.bird_y, time.time(), dead=(self.state == "OVER"))

    def draw(self):
        t = time.time()
        world = pygame.Surface((W, H))
        self.draw_world(world)
        self.draw_lights_on(world, t)

        # flash de relâmpago
        if self.flash > 0:
            ov = pygame.Surface((W, H))
            ov.fill((255, 120, 120))
            ov.set_alpha(int(110 * self.flash))
            world.blit(ov, (0, 0))

        # vinheta
        world.blit(self._vignette(), (0, 0))

        ox = random.randint(-int(self.shake), int(self.shake)) if self.shake > 1 else 0
        oy = random.randint(-int(self.shake), int(self.shake)) if self.shake > 1 else 0
        self.screen.fill((0, 0, 0))
        self.screen.blit(world, (ox, oy))

        self.draw_hud()
        if self.state == "WAIT":
            self.draw_title()
        elif self.state == "OVER":
            self.draw_gameover()
        pygame.display.flip()

    def draw_lights_on(self, surf, t):
        old = self.screen
        self.screen = surf
        self.draw_lights(t)
        self.screen = old

    _vig = None

    def _vignette(self):
        if Game._vig is None:
            v = pygame.Surface((W, H), pygame.SRCALPHA)
            for i in range(60):
                a = int(150 * (1 - i / 60) ** 2)
                pygame.draw.rect(v, (0, 0, 0, a), (i, i, W - 2 * i, H - 2 * i), 1)
            Game._vig = v
        return Game._vig

    def draw_hud(self):
        if self.state == "PLAY":
            glow_text(self.screen, str(self.score), self.f_big, (W // 2, 120))
            sp = self.f_small.render(f"Velocidade {self.speed_mult:.1f}x", True, BONE)
            self.screen.blit(sp, sp.get_rect(center=(W // 2, 165)))
        # status do sensor
        if self.sim:
            txt, col = "MODO SIMULAÇÃO (mouse)", (255, 200, 80)
        else:
            d = self.sensor.read() if self.sensor else None
            if d is None:
                txt, col = "SENSOR: sem leitura", (255, 90, 90)
            else:
                txt, col = f"SENSOR: {d:5.1f} cm", (120, 255, 150)
        s = self.f_tiny.render(txt, True, col)
        self.screen.blit(s, (12, H - 22))
        b = self.f_tiny.render(f"Recorde: {self.best}", True, BONE)
        self.screen.blit(b, (W - b.get_width() - 12, H - 22))

    def draw_title(self):
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((0, 0, 0, 110))
        self.screen.blit(shade, (0, 0))
        glow_text(self.screen, "STRANGER", self.f_title, (W // 2, 200), spread=5)
        glow_text(self.screen, "FLAPPY", self.f_title, (W // 2, 265), spread=5)
        sub = self.f_mid.render("Fuja do Mundo Invertido", True, BONE)
        self.screen.blit(sub, sub.get_rect(center=(W // 2, 330)))
        blink = int(time.time() * 2) % 2 == 0
        if blink:
            msg = self.f_small.render(
                "Mova a mão sobre o sensor para voar  -  ESPAÇO ou clique para começar", True, (255, 210, 120))
            self.screen.blit(msg, msg.get_rect(center=(W // 2, 395)))

    def draw_gameover(self):
        shade = pygame.Surface((W, H), pygame.SRCALPHA)
        shade.fill((20, 0, 0, 140))
        self.screen.blit(shade, (0, 0))
        panel = pygame.Rect(0, 0, 520, 300)
        panel.center = (W // 2, H // 2 + 10)
        pygame.draw.rect(self.screen, (18, 6, 10), panel, border_radius=18)
        pygame.draw.rect(self.screen, BLOOD, panel, 4, border_radius=18)
        glow_text(self.screen, "GAME OVER", self.f_title, (W // 2, panel.top + 62), spread=4)
        sub = self.f_small.render("O Demogorgon te pegou!", True, BONE)
        self.screen.blit(sub, sub.get_rect(center=(W // 2, panel.top + 112)))
        sc = self.f_mid.render(f"Pontos: {self.score}", True, (255, 255, 255))
        self.screen.blit(sc, sc.get_rect(center=(W // 2, panel.top + 160)))
        txt = "NOVO RECORDE!" if self.new_record else f"Recorde: {self.best}"
        bs = self.f_mid.render(txt, True, (255, 210, 90) if self.new_record else VINE_LIGHT)
        self.screen.blit(bs, bs.get_rect(center=(W // 2, panel.top + 205)))
        if self.dead_t > 0.6:
            r = self.f_small.render("ESPAÇO ou clique para tentar de novo", True, BONE)
            self.screen.blit(r, r.get_rect(center=(W // 2, panel.top + 260)))

    # -- loop principal
    def run(self):
        running = True
        while running:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    running = False
                elif e.type == pygame.KEYDOWN:
                    if e.key == pygame.K_ESCAPE:
                        running = False
                    elif e.key == pygame.K_SPACE:
                        self._action()
                    elif e.key == pygame.K_m and self.sensor:
                        self.sim = not self.sim
                elif e.type == pygame.MOUSEBUTTONDOWN:
                    self._action()
            self.update(dt)
            self.draw()
        pygame.quit()

    def _action(self):
        if self.state == "WAIT" or (self.state == "OVER" and self.dead_t > 0.6):
            self.start()


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="Stranger Flappy - controlado por sensor ultrassônico")
    ap.add_argument("--port", help="porta serial (ex.: COM3, /dev/ttyACM0). Padrão: detectar")
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--sim", action="store_true", help="joga com o mouse, sem Arduino")
    args = ap.parse_args()

    sensor = None
    sim = args.sim
    if not sim:
        sensor = Sensor(args.port, args.baud)
        if sensor.start():
            print(f"[ok] Arduino em {sensor.port}")
        else:
            print(f"[aviso] {sensor.error}. Iniciando em modo simulação (mouse).")
            sensor = None
            sim = True

    game = Game(sensor, sim)
    try:
        game.run()
    finally:
        if sensor:
            sensor.close()


if __name__ == "__main__":
    main()