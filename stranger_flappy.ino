/*
  STRANGER FLAPPY - Arduino UNO 
  ------------------------------------------------------------------
  Ligações:
     HC-SR04 VCC  -> 5V
     HC-SR04 GND  -> GND
     HC-SR04 TRIG -> D9
     HC-SR04 ECHO -> D10

  Envia pela serial (115200 baud), ~25 vezes por segundo:
     D:12.3     distância em cm
     D:-1       sem leitura / fora de alcance
  O script Python lê essas linhas. Não precisa enviar nada de volta.
*/

const uint8_t PIN_TRIG = 9;
const uint8_t PIN_ECHO = 10;

const unsigned long BAUD           = 115200;
const unsigned long PING_INTERVAL  = 40;      // ms entre disparos
const unsigned long ECHO_TIMEOUT   = 30000UL; // us (~5 m)
const float         MAX_CM         = 200.0;   // acima disso = inválido
const float         MIN_CM         = 2.0;     // abaixo disso = inválido (ruído)

float hist[3] = {-1, -1, -1};   // últimas 3 leituras para a mediana
uint8_t hidx = 0;
uint8_t failCount = 0;
unsigned long lastPing = 0;

float pingOnce() {
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(5);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  unsigned long dur = pulseIn(PIN_ECHO, HIGH, ECHO_TIMEOUT);
  if (dur == 0) return -1.0;
  float cm = dur / 58.0;          // us -> cm
  if (cm < MIN_CM || cm > MAX_CM) return -1.0;
  return cm;
}

// Mediana das últimas 3 leituras 
float median3(float a, float b, float c) {
  if ((a <= b && b <= c) || (c <= b && b <= a)) return b;
  if ((b <= a && a <= c) || (c <= a && a <= b)) return a;
  return c;
}

void setup() {
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);
  digitalWrite(PIN_TRIG, LOW);
  Serial.begin(BAUD);
  delay(100);
  Serial.println("READY");
}

void loop() {
  unsigned long now = millis();
  if (now - lastPing < PING_INTERVAL) return;
  lastPing = now;

  float d = pingOnce();

  // Se o sensor falhar várias vezes seguidas, tenta "destravar" o ECHO
  if (d < 0) {
    if (++failCount >= 10) {
      pinMode(PIN_ECHO, OUTPUT);
      digitalWrite(PIN_ECHO, LOW);
      delay(5);
      pinMode(PIN_ECHO, INPUT);
      failCount = 0;
    }
  } else {
    failCount = 0;
  }

  hist[hidx] = d;
  hidx = (hidx + 1) % 3;

  float out;
  if (hist[0] < 0 || hist[1] < 0 || hist[2] < 0) {
    out = d;                              // enquanto o histórico não está cheio/válido
  } else {
    out = median3(hist[0], hist[1], hist[2]);
  }

  Serial.print("D:");
  Serial.println(out, 1);
}
