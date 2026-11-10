// =============================================================================
// medicoes.ino  --  Arduino Uno + sensor ultrassonico HC-SR04
//
// O Arduino NAO calcula media, filtro nem distancia: ele apenas mede o tempo
// de eco (em microssegundos) toda vez que o computador envia o caractere 'M'
// e devolve esse numero pela porta serial. A conversao para distancia e feita
// no programa Python (coleta_dados.py).
//
// Resposta a cada pedido 'M':
//   - tempo de eco em microssegundos (ex.: 5780)
//   - 0 se nenhum eco foi recebido dentro do tempo limite (perda de leitura)
//
// Ligacoes:  HC-SR04 VCC -> 5V | GND -> GND | TRIG -> pino 9 | ECHO -> pino 10
// =============================================================================

const uint8_t PINO_TRIG = 9;
const uint8_t PINO_ECHO = 10;
const unsigned long TEMPO_LIMITE_US = 30000UL;  // 30 ms (~5 m de ida e volta)

unsigned long medirTempoEco() {
  // Pulso de 10 us no TRIG (precedido de um nivel baixo limpo)
  digitalWrite(PINO_TRIG, LOW);
  delayMicroseconds(4);
  digitalWrite(PINO_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PINO_TRIG, LOW);

  // Duracao do pulso em ECHO = tempo de ida e volta do som
  // (pulseIn devolve 0 se estourar o tempo limite)
  return pulseIn(PINO_ECHO, HIGH, TEMPO_LIMITE_US);
}

void setup() {
  pinMode(PINO_TRIG, OUTPUT);
  pinMode(PINO_ECHO, INPUT);
  digitalWrite(PINO_TRIG, LOW);

  Serial.begin(115200);
  delay(100);
  Serial.println(F("HCSR04_PRONTO"));  // sinal para o Python de que a placa esta pronta
}

void loop() {
  if (Serial.available() > 0) {
    char comando = Serial.read();
    if (comando == 'M') {
      unsigned long tempo_us = medirTempoEco();
      Serial.println(tempo_us);
    }
  }
}
