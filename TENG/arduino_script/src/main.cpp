#include <AccelStepper.h>

#define PUL_PIN 9
#define DIR_PIN 8
#define ENA_PIN 7
#define END_STOP_PIN_1 5
#define AUTO_TRIGGER_PIN 3
#define FORCE_PIN A0

#define MAX_SPEED 4000
#define ACCELERATION 8000
#define SLOW_SPEED 100
#define SLEEP_TIME 3000
#define WAIT_TIME 1000
#define BACKUP_STEPS 125
#define FORWARD_STEPS 130
#define DEBOUNCE_DELAY 50
#define STATUS_INTERVAL_MS 200

// Steps per cm: 130 steps ≈ 1.5 cm → 86.67 steps/cm
#define STEPS_PER_CM 86.67f

// Set FORCE_SENSOR_ENABLED to true and tune FORCE_SCALE for your sensor.
// With no sensor connected, pull A0 to GND or leave FORCE_SENSOR_ENABLED false.
#define FORCE_SENSOR_ENABLED false
#define FORCE_SCALE 0.488f  // ADC counts → grams (sensor-specific, tune this)

AccelStepper stepper(AccelStepper::DRIVER, PUL_PIN, DIR_PIN);

unsigned long lastTriggerTime = 0;
bool lastTriggerState = LOW;
unsigned long lastStatusTime = 0;
const char* currentDir = "idle";

void printStatus() {
    float pos = -(float)stepper.currentPosition() / STEPS_PER_CM;
    if (pos < 0.0f) pos = 0.0f;
    Serial.print("STATUS pos_cm=");
    Serial.print(pos, 2);
    Serial.print(" dir=");
    Serial.println(currentDir);
}

void moveStepper(int steps) {
    digitalWrite(ENA_PIN, LOW);
    stepper.move(steps);
    while (stepper.distanceToGo() != 0) {
        if (steps < 0 && digitalRead(END_STOP_PIN_1) == LOW) {
            stepper.stop();
            return;
        }
        stepper.run();
    }
}

void autoCycle() {
    currentDir = "forward";
    digitalWrite(ENA_PIN, LOW);
    stepper.setMaxSpeed(MAX_SPEED);
    stepper.setAcceleration(ACCELERATION);
    stepper.move(-FORWARD_STEPS);

    int peakForceRaw = 0;
    while (stepper.distanceToGo() != 0) {
        stepper.run();
#if FORCE_SENSOR_ENABLED
        int raw = analogRead(FORCE_PIN);
        if (raw > peakForceRaw) peakForceRaw = raw;
#endif
        if (digitalRead(END_STOP_PIN_1) == LOW) {
            stepper.setCurrentPosition(stepper.currentPosition());
            break;
        }
    }

    float impactPos = -(float)stepper.currentPosition() / STEPS_PER_CM;
    if (impactPos < 0.0f) impactPos = 0.0f;
    float peakForce_g = peakForceRaw * FORCE_SCALE;

    currentDir = "idle";
    delay(WAIT_TIME);

    currentDir = "backward";
    stepper.setMaxSpeed(SLOW_SPEED);
    stepper.move(BACKUP_STEPS);
    while (stepper.distanceToGo() != 0) {
        stepper.run();
    }

    stepper.setCurrentPosition(0);
    currentDir = "idle";
    digitalWrite(ENA_PIN, HIGH);

    Serial.print("IMPACT peak_g=");
    Serial.print(peakForce_g, 1);
    Serial.print(" pos_cm=");
    Serial.println(impactPos, 2);

    delay(SLEEP_TIME);
}

void setup() {
    pinMode(ENA_PIN, OUTPUT);
    digitalWrite(ENA_PIN, LOW);
    pinMode(END_STOP_PIN_1, INPUT_PULLUP);
    pinMode(AUTO_TRIGGER_PIN, INPUT);
#if FORCE_SENSOR_ENABLED
    pinMode(FORCE_PIN, INPUT);
#endif
    stepper.setPinsInverted(true, false, false);
    stepper.setMaxSpeed(MAX_SPEED);
    stepper.setAcceleration(ACCELERATION);
    Serial.begin(115200);
    Serial.println("STATUS pos_cm=0.00 dir=idle");
}

void loop() {
    if (millis() - lastStatusTime >= STATUS_INTERVAL_MS) {
        printStatus();
        lastStatusTime = millis();
    }

    bool currentTriggerState = digitalRead(AUTO_TRIGGER_PIN);
    if (currentTriggerState == HIGH && lastTriggerState == LOW) {
        if (millis() - lastTriggerTime > DEBOUNCE_DELAY) {
            autoCycle();
            lastTriggerTime = millis();
        }
    }
    lastTriggerState = currentTriggerState;

    if (Serial.available() > 0) {
        int input = Serial.parseInt();
        while (Serial.available() > 0) Serial.read();
        if (input == 1) {
            autoCycle();
        } else if (input != 0) {
            currentDir = (input < 0) ? "forward" : "backward";
            moveStepper(input);
            currentDir = "idle";
        }
    }
}
