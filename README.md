# Incerteza e robustez na medição de distância com HC-SR04
### Uma abordagem investigativa com Arduino e jogo eletrônico

![XII EXPOTEC](https://img.shields.io/badge/XII%20EXPOTEC-2026-red)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Arduino](https://img.shields.io/badge/arduino-UNO-teal)
![Licença](https://img.shields.io/badge/licen%C3%A7a-MIT-green)

Este repositório reúne o código, os dados e a análise estatística de um projeto
desenvolvido por estudantes da **2ª série do Ensino Médio** da Escola Estadual
Rosa Pignataro (Nova Cruz/RN) para a **XII EXPOTEC**. O objetivo foi investigar
*como* o sensor ultrassônico HC-SR04 erra e *como lidar com esse erro* em uma
aplicação real: um jogo inspirado em *Flappy Bird*, com tema de *Stranger Things*,
controlado pela altura da mão.

## 🔬 O que foi investigado

- **1000 medições** em cada uma de quatro distâncias reais (5, 10, 15 e 20 cm),
  com alvo fixo medido por trena.
- **Teste de Shapiro-Wilk** e análise de assimetria/curtose para verificar se
  os erros seguem distribuição gaussiana.
- **Histogramas e gráficos Q-Q** por distância.
- **Regressão linear** do viés e da dispersão em função da distância.
- **Autocorrelação** (lag-1) para verificar independência das leituras.
- **Comparação** entre média, mediana e leituras isoladas.

### Principais resultados

| Grandeza | Faixa observada |
|---|---|
| Erro médio (viés) | −7,6 a −1,8 mm |
| Desvio-padrão | 0,46 a 2,01 mm |
| Rejeições de normalidade (Shapiro-Wilk, p < 0,05) | **4 / 4 distâncias** |
| Curtose em excesso | −1,03 a **+19,69** (caudas pesadas) |

Os erros **não são gaussianos**: concentram-se em poucos valores (discretização do
relógio do Arduino) e incluem leituras afastadas que deslocam a média. Por isso, o
jogo adotou a **mediana de três leituras** como estimador robusto.

## 🎮 O jogo: Stranger Flappy

- A personagem (Eleven) sobe e desce conforme a **altura da mão** sobre o HC-SR04.
- Faixa calibrada: **6 a 36 cm** (mapeada linearmente para a tela).
- Vinhas do Mundo Invertido com "bocas de Demogorgon", relâmpagos e esporos.
- Modo `--sim` permite jogar **sem Arduino**, usando o mouse.
- Recorde persistido em `best.json`.

## 📁 Estrutura do repositório
├── artigo/ # PDF do manuscrito (XII EXPOTEC)
│ └── incerteza_robustez_hcsr04.pdf
├── coleta_dados.py # GUI Tkinter para coleta (Arduino + trena)
├── executar_app.cmd # Atalho Windows para rodar a coleta
├── medicoes.ino # Firmware Arduino: só mede tempo de eco
├── stranger_flappy.py # Jogo em Pygame
├── stranger_flappy.ino # Firmware Arduino: envia D:distância
├── analise_dados.ipynb # Notebook com toda a análise estatística
├── dado_experimental_*cm.csv # Dados brutos (gerados pela coleta)
└── README.md


## ⚙️ Requisitos

### Hardware
- Arduino Uno (ou compatível)
- Sensor HC-SR04
- Jumpers: `VCC → 5V`, `GND → GND`, `TRIG → D9`, `ECHO → D10`

### Software
```bash
pip install pyserial pygame numpy pandas scipy matplotlib jupyter
```
## 🚀 Como usar
1. Coletar dados (experimento)
bash
# Windows
executar_app.cmd

1. Carregue medicoes.ino no Arduino.
2. Posicione o alvo e meça com a trena.
3. Informe a distância no programa e clique em COLETAR DADOS.
4. O arquivo dado_experimental_Dcm.csv será gerado.

## Analisar os dados
```bash
jupyter notebook analise_dados.ipynb
```
O notebook gera todas as tabelas, figuras e números do artigo (histogramas,
Q-Q, testes de Shapiro-Wilk, regressões, autocorrelação etc.).

## Jogar 
```bash
# Carregue stranger_flappy.ino no Arduino primeiro
python stranger_flappy.py                    # autodetecta a porta
python stranger_flappy.py --sim              # sem Arduino (mouse)
```
Teclas: ESPAÇO/clique inicia ou reinicia · M alterna mouse/sensor · ESC sai.


