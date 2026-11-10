"""
coleta_dados.py -- Coleta de medidas do sensor HC-SR04 (Arduino Uno)

Uso:  python coleta_dados.py

1. Posicione o alvo e meça a distancia real com a trena (face do sensor ate a
   face do alvo).
2. Digite a distancia em centimetros e clique em COLETAR DADOS.
3. O programa faz N_MEDICOES leituras, uma a cada INTERVALO_S segundos, e grava
   o arquivo  dado_experimental_Dcm.csv  (D = distancia informada) com as colunas:
       medida_cm : distancia medida pelo sensor (vazio = leitura sem eco)
       erro_cm   : medida_cm - distancia informada

Requisitos:  pip install pyserial   (o tkinter ja vem com o Python)
"""

import csv
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

try:
    import serial
    from serial.tools import list_ports
except ImportError:
    raise SystemExit("Biblioteca 'pyserial' nao encontrada. Instale com:  pip install pyserial")

# ------------------------------ CONFIGURACAO ---------------------------------
PORTA_SERIAL = None        # ex.: "COM3" ou "/dev/ttyACM0"; None = detectar sozinho
BAUD = 115200
N_MEDICOES = 1000
INTERVALO_S = 0.05        # 50 ms entre leituras
TEMPERATURA_C = 25.0       # AJUSTE para a temperatura da sala durante a coleta
TIMEOUT_RESPOSTA_S = 0.3   # tempo maximo esperando a resposta do Arduino
PASTA_SAIDA = os.path.dirname(os.path.abspath(__file__))
# -----------------------------------------------------------------------------


def velocidade_som(temperatura_c):
    """Velocidade do som no ar (m/s): c ~ 331 + 0,6 T."""
    return 331.0 + 0.6 * temperatura_c


def tempo_para_distancia_cm(tempo_us, temperatura_c):
    """Converte o tempo de eco (us) em distancia (cm): d = c * t / 2."""
    return velocidade_som(temperatura_c) * tempo_us * 5e-5


def nome_arquivo(distancia_cm):
    return f"dado_experimental_{distancia_cm:g}cm.csv"


def encontrar_porta():
    if PORTA_SERIAL:
        return PORTA_SERIAL
    portas = list(list_ports.comports())
    palavras = ("arduino", "ch340", "usb serial", "usb-serial", "ftdi", "acm")
    for p in portas:
        texto = f"{p.description} {p.manufacturer or ''} {p.device}".lower()
        if any(k in texto for k in palavras):
            return p.device
    return portas[0].device if portas else None


class Coletor(threading.Thread):
    """Executa a coleta em segundo plano para a janela nao travar."""

    def __init__(self, distancia_cm, fila, parar):
        super().__init__(daemon=True)
        self.distancia_cm = distancia_cm
        self.fila = fila
        self.parar = parar

    def run(self):
        try:
            self._executar()
        except Exception as exc:  # qualquer problema vira mensagem na janela
            self.fila.put(("erro", str(exc)))

    def _aguardar_arduino(self, ser):
        fim = time.time() + 6.0
        while time.time() < fim:
            linha = ser.readline().decode(errors="ignore").strip()
            if linha == "HCSR04_PRONTO":
                time.sleep(0.5)
                return
        # Plano B: a placa pode nao ter reiniciado; testa uma medida
        ser.reset_input_buffer()
        ser.write(b"M")
        linha = ser.readline().decode(errors="ignore").strip()
        if linha.isdigit():
            return
        raise RuntimeError(
            "O Arduino nao respondeu. Verifique o cabo USB, a porta serial e se o "
            "codigo medicoes.ino foi carregado na placa."
        )

    def _executar(self):
        porta = encontrar_porta()
        if porta is None:
            raise RuntimeError("Nenhuma porta serial encontrada. Conecte o Arduino por USB.")
        self.fila.put(("status", f"Conectando em {porta}..."))

        caminho_final = os.path.join(PASTA_SAIDA, nome_arquivo(self.distancia_cm))
        caminho_tmp = caminho_final + ".tmp"
        feitas = 0
        perdas = 0
        falhas_seguidas = 0

        with serial.Serial(porta, BAUD, timeout=TIMEOUT_RESPOSTA_S) as ser:
            self._aguardar_arduino(ser)
            self.fila.put(("status", "Coletando..."))

            with open(caminho_tmp, "w", newline="", encoding="utf-8") as f:
                escritor = csv.writer(f)
                escritor.writerow(["medida_cm", "erro_cm"])
                inicio = time.perf_counter()

                for i in range(N_MEDICOES):
                    if self.parar.is_set():
                        break
                    # agenda fixa: a leitura i ocorre em inicio + i * INTERVALO_S
                    espera = inicio + i * INTERVALO_S - time.perf_counter()
                    if espera > 0:
                        time.sleep(espera)

                    ser.reset_input_buffer()
                    ser.write(b"M")
                    linha = ser.readline().decode(errors="ignore").strip()

                    medida = None
                    if linha == "":
                        falhas_seguidas += 1
                        if falhas_seguidas >= 20:
                            raise RuntimeError("O Arduino parou de responder (20 falhas seguidas).")
                    else:
                        falhas_seguidas = 0
                        if linha.isdigit() and int(linha) > 0:
                            medida = tempo_para_distancia_cm(int(linha), TEMPERATURA_C)

                    if medida is None:
                        perdas += 1
                        escritor.writerow(["", ""])
                    else:
                        escritor.writerow([f"{medida:.4f}", f"{medida - self.distancia_cm:.4f}"])
                    feitas += 1

                    if feitas % 100 == 0:
                        f.flush()
                    self.fila.put(("progresso", feitas, perdas, medida))

        completo = feitas == N_MEDICOES
        if completo:
            os.replace(caminho_tmp, caminho_final)
            destino = caminho_final
        else:
            destino = caminho_final.replace(".csv", "_incompleto.csv")
            os.replace(caminho_tmp, destino)
        self.fila.put(("fim", destino, feitas, perdas, completo))


class Botao(tk.Label):
    """Botao colorido (tk.Label funciona com cores em Windows, Linux e macOS)."""

    def __init__(self, master, texto, cor, comando):
        super().__init__(master, text=texto, bg=cor, fg="white",
                         font=("Arial", 13, "bold"), padx=18, pady=10,
                         relief="raised", bd=3, cursor="hand2")
        self.cor, self.comando, self.ativo = cor, comando, True
        self.bind("<Button-1>", lambda _e: self.comando() if self.ativo else None)

    def definir_ativo(self, ativo):
        self.ativo = ativo
        self.config(bg=self.cor if ativo else "#9e9e9e", cursor="hand2" if ativo else "arrow")


class App:
    def __init__(self, root):
        self.root = root
        root.title("Coleta de dados - HC-SR04")
        root.resizable(False, False)
        self.fila = queue.Queue()
        self.parar = threading.Event()
        self.coletor = None

        quadro = tk.Frame(root, padx=20, pady=16)
        quadro.pack()

        tk.Label(quadro, text="Informe a posição do alvo em centímetros:",
                 font=("Arial", 12)).pack(anchor="w")
        self.var_dist = tk.StringVar()
        self.entrada = tk.Entry(quadro, textvariable=self.var_dist, font=("Arial", 14), width=12)
        self.entrada.pack(anchor="w", pady=(4, 12))
        self.entrada.focus_set()
        self.entrada.bind("<Return>", lambda _e: self.coletar())

        botoes = tk.Frame(quadro)
        botoes.pack(pady=(0, 10))
        self.btn_sair = Botao(botoes, "SAIR", "#d32f2f", self.sair)
        self.btn_sair.pack(side="left", padx=(0, 12))
        self.btn_coletar = Botao(botoes, "COLETAR DADOS", "#2e7d32", self.coletar)
        self.btn_coletar.pack(side="left")

        self.barra = ttk.Progressbar(quadro, length=330, maximum=N_MEDICOES)
        self.barra.pack(pady=(6, 4))
        self.var_status = tk.StringVar(value=f"Pronto. Cada coleta leva cerca de "
                                             f"{N_MEDICOES * INTERVALO_S / 60:.1f} min.")
        tk.Label(quadro, textvariable=self.var_status, font=("Arial", 10),
                 wraplength=330, justify="left").pack(anchor="w")

        root.protocol("WM_DELETE_WINDOW", self.sair)
        self._verificar_fila()

    # --------------------------------------------------------------------
    def coletar(self):
        if self.coletor is not None and self.coletor.is_alive():
            return
        texto = self.var_dist.get().strip().replace(",", ".")
        try:
            distancia = float(texto)
            if not 1.0 <= distancia <= 400.0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Distância inválida",
                                 "Digite um número entre 1 e 400 (em centímetros), por exemplo: 50")
            return

        destino = os.path.join(PASTA_SAIDA, nome_arquivo(distancia))
        if os.path.exists(destino):
            if not messagebox.askyesno("Arquivo existente",
                                       f"{os.path.basename(destino)} já existe.\nSubstituir?"):
                return

        self.barra["value"] = 0
        self.entrada.config(state="disabled")
        self.btn_coletar.definir_ativo(False)
        self.parar.clear()
        self.coletor = Coletor(distancia, self.fila, self.parar)
        self.coletor.start()

    def sair(self):
        if self.coletor is not None and self.coletor.is_alive():
            if not messagebox.askyesno("Coleta em andamento",
                                       "Interromper a coleta e sair?\n"
                                       "Os dados já coletados serão salvos em um arquivo *_incompleto.csv."):
                return
            self.parar.set()
            self.coletor.join(timeout=3)
        self.root.destroy()

    def _liberar(self):
        self.entrada.config(state="normal")
        self.btn_coletar.definir_ativo(True)
        self.entrada.focus_set()

    def _verificar_fila(self):
        try:
            while True:
                msg = self.fila.get_nowait()
                tipo = msg[0]
                if tipo == "status":
                    self.var_status.set(msg[1])
                elif tipo == "progresso":
                    _, feitas, perdas, ultima = msg
                    self.barra["value"] = feitas
                    ultima_txt = "sem eco" if ultima is None else f"{ultima:.2f} cm"
                    self.var_status.set(f"Medição {feitas}/{N_MEDICOES} | perdas: {perdas} | "
                                        f"última: {ultima_txt}")
                elif tipo == "fim":
                    _, destino, feitas, perdas, completo = msg
                    self._liberar()
                    if completo:
                        self.var_status.set("Coleta concluída.")
                        messagebox.showinfo("Coleta concluída",
                                            f"{feitas} medições ({perdas} sem eco).\n"
                                            f"Arquivo salvo:\n{destino}")
                    else:
                        self.var_status.set("Coleta interrompida.")
                elif tipo == "erro":
                    self._liberar()
                    self.var_status.set("Erro na coleta.")
                    messagebox.showerror("Erro", msg[1])
        except queue.Empty:
            pass
        self.root.after(100, self._verificar_fila)


if __name__ == "__main__":
    janela = tk.Tk()
    App(janela)
    janela.mainloop()
