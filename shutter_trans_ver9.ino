// Pin definitions
#define Q_SWITCH_PIN       12
#define SHUTTER_PIN         5
#define ENABLE_PIN          4
// X-axis
#define X_STEP_PIN          2
#define X_DIR_PIN           6
#define X_LIMIT_NEAR_PIN    9
#define X_LIMIT_FAR_PIN     8
// Z-axis
#define Z_STEP_PIN          3
#define Z_DIR_PIN           7
#define Z_LIMIT_NEAR_PIN   11
#define Z_LIMIT_FAR_PIN    10

// Motion constants
#define STEPS_PER_MM        200
#define X_STEP_DELAY_US    1000   // 1 ms pulse for X-axis
#define Z_STEP_DELAY_US    700   // 2 ms pulse for Z-axis (slower)

// Q-switch timeout (ms)
#define QS_TIMEOUT_MS     5000

// Globals set via PC GUI
int   g_positions      = 0;
int   g_pulsesPerSpot  = 0;
float g_dx             = 0;
float g_dz             = 0;
bool  g_xForward       = true;
bool  g_zForward       = true;

// Position tracking (in steps)
long  g_xPosSteps     = 0;
long  g_zPosSteps     = 0;

// Convert steps to mm
float stepsToMm(long steps) {
  return float(steps) / STEPS_PER_MM;
}

// Robust Q-switch detection with edge validation
bool waitForQSwitch(unsigned long timeout_ms) {
  unsigned long start = millis();
  bool lastState = digitalRead(Q_SWITCH_PIN);
  
  while (true) {
    // Timeout check
    if (millis() - start > timeout_ms) return false;
    
    bool currentState = digitalRead(Q_SWITCH_PIN);
    
    // Detect HIGH→LOW transition
    if (lastState == HIGH && currentState == LOW) {
      // Verify LOW state after 10μs (anti-noise)
      delayMicroseconds(10);
      if (digitalRead(Q_SWITCH_PIN) == LOW) {
        return true; // Valid falling edge
      }
    }
    lastState = currentState;
  }
}

// Basic limit‐switch read with debounce (10 ms)
bool limitPressed(uint8_t pin) {
  if (digitalRead(pin) != LOW) return false;
  unsigned long t0 = millis();
  while (millis() - t0 < 10) {
    if (digitalRead(pin) != LOW) return false;
  }
  return true;
}

// Move one axis with axis-specific step delay
void moveAxis(uint8_t stepPin, uint8_t dirPin,
              uint8_t limFar, uint8_t limNear,
              float dist_mm, bool forward) {
  long totalSteps = lround(dist_mm * STEPS_PER_MM);
  uint8_t limitPin = forward ? limFar : limNear;

  // Pre-check limit
  if (limitPressed(limitPin)) {
    Serial.println(forward ? "Far end reached" : "Near end reached");
    return;
  }

  // Set direction
  digitalWrite(dirPin, forward ? HIGH : LOW);

  // Choose step delay based on axis
  unsigned long stepDelay = (stepPin == Z_STEP_PIN)
                             ? Z_STEP_DELAY_US
                             : X_STEP_DELAY_US;

  // Stepping loop
  for (long i = 0; i < totalSteps; i++) {
    if (limitPressed(limitPin)) {
      Serial.println(forward ? "Far end reached" : "Near end reached");
      break;
    }
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(stepDelay);
    digitalWrite(stepPin, LOW);
    delayMicroseconds(stepDelay);

    // Update step count
    if (stepPin == X_STEP_PIN) {
      g_xPosSteps += (forward ? 1 : -1);
    } else {
      g_zPosSteps += (forward ? 1 : -1);
    }
  }
}
void runSequence() {
  for (int pos = 0; pos < g_positions; pos++) {

    for (int p = 0; p < g_pulsesPerSpot; p++) {

      // 1) WAIT for NEXT from PC (with timeout)
      unsigned long wait_start = millis();
      const unsigned long NEXT_WAIT_MS = 10000UL; // 30s, adjust if needed
      bool got_next = false;
      while (millis() - wait_start < NEXT_WAIT_MS) {
        if (Serial.available()) {
          String s = Serial.readStringUntil('\n');
          s.trim();
          if (s.length() == 0) continue;
          // optional echo for debug
          Serial.print("CMD_RECV:"); Serial.println(s);
          if (s.equalsIgnoreCase("NEXT")) {
            got_next = true;
            break;
          }
          // If there are other commands you want to accept here (e.g. ABORT),
          // parse them and respond accordingly.
        }
        delay(5);
      }
      if (!got_next) {
        Serial.println("NEXT_TIMEOUT");
        // policy: abort sequence on timeout or continue; here we abort
        return;
      }

      // 2) Wait for Q-switch edge (blocking, validated by waitForQSwitch)
      if (!waitForQSwitch(QS_TIMEOUT_MS)) {
        Serial.println("QTIMEOUT");
        // choose to continue to next pulse or abort; here we continue
        return;
      }
      delay(50UL);

      // 3) Fire shutter AFTER Q-switch detection
      // Use a per-pulse open time (ms). Adjust to your shutter/laser timing.
      unsigned long open_ms = (35UL);  // <-- set appropriate per-pulse hold time (milliseconds)
      digitalWrite(SHUTTER_PIN, HIGH);
      delay(open_ms);
      digitalWrite(SHUTTER_PIN, LOW);

      // small settle so external systems (scope) can register the trace
      delay(30);

      // 4) Notify PC this pulse finished
      Serial.print("PULSE_DONE,");
      Serial.println(p + 1);

      // Loop will naturally go back to top and wait for NEXT again.
    }

    // after pulses for this position, move axes if required
    // (keep your existing moveAxis calls or use a MOV command from PC/GU I)
    moveAxis(X_STEP_PIN, X_DIR_PIN, X_LIMIT_FAR_PIN, X_LIMIT_NEAR_PIN, g_dx, g_xForward);
    Serial.print("X pos (mm): "); Serial.println(stepsToMm(g_xPosSteps), 3);

    moveAxis(Z_STEP_PIN, Z_DIR_PIN, Z_LIMIT_FAR_PIN, Z_LIMIT_NEAR_PIN, g_dz, g_zForward);
    Serial.print("Z pos (mm): "); Serial.println(stepsToMm(g_zPosSteps), 3);
  }

  Serial.println("DONE");
}

      


bool parseCommand(const String &s) {
  char buf[80]; s.toCharArray(buf, sizeof(buf));
  char* tok = strtok(buf, ","); if (!tok) return false; g_positions     = atoi(tok);
  tok = strtok(nullptr, ","); if (!tok) return false; g_pulsesPerSpot = atoi(tok);
  tok = strtok(nullptr, ","); if (!tok) return false; g_dx            = atof(tok);
  tok = strtok(nullptr, ","); if (!tok) return false; g_dz            = atof(tok);
  tok = strtok(nullptr, ","); if (!tok) return false; g_xForward      = (tok[0]=='F');
  tok = strtok(nullptr, ","); if (!tok) return false; g_zForward      = (tok[0]=='F');
  return true;
}

bool parseManualMove(const String &s) {
  char buf[40]; s.toCharArray(buf, sizeof(buf));
  char* tok = strtok(buf, ","); if (!tok) return false;
  char axis = tok[0];
  tok = strtok(nullptr, ","); if (!tok) return false; float dist = atof(tok);
  tok = strtok(nullptr, ","); if (!tok) return false; bool dir  = (tok[0]=='F');

  if      (axis=='X') moveAxis(X_STEP_PIN, X_DIR_PIN, X_LIMIT_FAR_PIN, X_LIMIT_NEAR_PIN, dist, dir);
  else if (axis=='Z') moveAxis(Z_STEP_PIN, Z_DIR_PIN, Z_LIMIT_FAR_PIN, Z_LIMIT_NEAR_PIN, dist, dir);
  else                return false;

  return true;
}

void setup() {
  Serial.begin(115200);
  pinMode(Q_SWITCH_PIN,     INPUT);
  pinMode(X_LIMIT_NEAR_PIN, INPUT_PULLUP);
  pinMode(X_LIMIT_FAR_PIN,  INPUT_PULLUP);
  pinMode(Z_LIMIT_NEAR_PIN, INPUT_PULLUP);
  pinMode(Z_LIMIT_FAR_PIN,  INPUT_PULLUP);
  pinMode(SHUTTER_PIN,      OUTPUT);
  pinMode(ENABLE_PIN,       OUTPUT);
  pinMode(X_STEP_PIN,       OUTPUT);
  pinMode(X_DIR_PIN,        OUTPUT);
  pinMode(Z_STEP_PIN,       OUTPUT);
  pinMode(Z_DIR_PIN,        OUTPUT);

  digitalWrite(SHUTTER_PIN, LOW);
  digitalWrite(ENABLE_PIN,  HIGH);
  Serial.println("READY");
}

void loop() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n');
  cmd.trim();

  if (cmd.startsWith("SEQ,")) {
    if (parseCommand(cmd.substring(4))) {
      runSequence();
      Serial.println("DONE");
    } else {
      Serial.println("ERROR");
    }
  }
  else if (cmd.startsWith("MOV,")) {
    if (parseManualMove(cmd.substring(4))) {
      Serial.println("MOVED");
      Serial.print("X pos (mm): "); Serial.println(stepsToMm(g_xPosSteps), 3);
      Serial.print("Z pos (mm): "); Serial.println(stepsToMm(g_zPosSteps), 3);
    } else {
      Serial.println("INVALID MOVE");
    }
  }
  else if (cmd.equalsIgnoreCase("MANUAL_OPEN")) {
    // Manual shutter open (no Q-switch detection)
    digitalWrite(SHUTTER_PIN, HIGH);
    Serial.println("SHUTTER_OPENED");
  }
  else if (cmd.equalsIgnoreCase("MANUAL_CLOSE")) {
    // Manual shutter close
    digitalWrite(SHUTTER_PIN, LOW);
    Serial.println("SHUTTER_CLOSED");
  }
  else {
    Serial.println("UNKNOWN CMD");
  }
}