#include <AccelStepper.h>
// Pin configuration
#define PUL_PIN 9   // Step (Pulse) pin
#define DIR_PIN 8   // Direction pin
#define ENA_PIN 7   // Enable pin (optional)
#define END_STOP_PIN_1 5  // Left end stop switch pin
// #define END_STOP_PIN_2 13  // Right end stop switch pin (Removed)
#define AUTO_TRIGGER_PIN 3 // Digital input to trigger autoCycle()
// Stepper configuration
#define MAX_SPEED 4000    // Max speed in steps per second
#define ACCELERATION 8000 // Acceleration in steps per second^2
#define SLOW_SPEED 100    // Slower speed for return movement
#define SLEEP_TIME 3000   // Delay at the end of autoCycle (in ms)
#define WAIT_TIME 1000    // Wait time before return movement (in ms)
#define BACKUP_STEPS 125  // Steps to move back (approx 1.5cm)
#define FORWARD_STEPS 130 // Steps to move forward (approx 1.5cm + margin)
#define DEBOUNCE_DELAY 50      // Debounce delay for trigger pin (in ms)
// Create stepper instance
AccelStepper stepper(AccelStepper::DRIVER, PUL_PIN, DIR_PIN);

// Debouncing variables
unsigned long lastTriggerTime = 0;
bool lastTriggerState = LOW;
void setup() {
    pinMode(ENA_PIN, OUTPUT);
    digitalWrite(ENA_PIN, LOW); // Enable driver (active LOW)
    pinMode(END_STOP_PIN_1, INPUT_PULLUP);
    // pinMode(END_STOP_PIN_2, INPUT_PULLUP); // Removed
    pinMode(AUTO_TRIGGER_PIN, INPUT); // Trigger pin for autoCycle()
    stepper.setPinsInverted(true, false, false);
    stepper.setMaxSpeed(MAX_SPEED);
    stepper.setAcceleration(ACCELERATION);
    Serial.begin(115200);
    Serial.println("Stepper Ready. Enter steps (positive for forward, negative for backward), or '1' for auto-cycle.");
}
void moveStepper(int steps) {
    digitalWrite(ENA_PIN, LOW); // Ensure driver is enabled
    stepper.move(steps);
    unsigned long startTime = millis();
    while (stepper.distanceToGo() != 0) {
        if (steps < 0 && digitalRead(END_STOP_PIN_1) == LOW) {
            Serial.println("End stop 1 (left) triggered! Stopping negative movement.");
            stepper.stop();
            return;
        }
        stepper.run();
    }
    unsigned long duration = millis() - startTime;
    if (duration > 0) {
        float speed = (float)abs(steps) / (duration / 1000.0);
        Serial.print("Move completed. Speed: ");
        Serial.print(speed);
        Serial.println(" steps/sec");
    } else {
        Serial.println("Move completed.");
    }
}
void autoCycle() {
    Serial.println("Auto-cycle started: Moving negative 100 steps or until end stop 1...");
    digitalWrite(ENA_PIN, LOW); // Re-enable driver
    stepper.setMaxSpeed(MAX_SPEED);
    stepper.setAcceleration(ACCELERATION);
    stepper.move(-FORWARD_STEPS);  // Move only ~100 steps
    while (stepper.distanceToGo() != 0) {
        stepper.run();
        if (digitalRead(END_STOP_PIN_1) == LOW) {
            Serial.println("End stop 1 reached. Stopping early.");
            stepper.setCurrentPosition(stepper.currentPosition()); // Immediate stop
            break;
        }
    }
    Serial.print("Waiting ");
    Serial.print(WAIT_TIME);
    Serial.println("ms...");
    delay(WAIT_TIME);
    Serial.println("Moving back slowly...");
    stepper.setMaxSpeed(SLOW_SPEED);
    stepper.move(BACKUP_STEPS);  // Move back fixed distance
    while (stepper.distanceToGo() != 0) {
        stepper.run();
    }
    Serial.println("Return complete. Resetting position and disabling stepper.");
    stepper.setCurrentPosition(0);
    digitalWrite(ENA_PIN, HIGH);  // Disable driver
    Serial.print("Sleeping for ");
    Serial.print(SLEEP_TIME);
    Serial.println("ms...");
    delay(SLEEP_TIME);
}
void loop() {
    // Trigger autoCycle from pin 3 with debouncing
    bool currentTriggerState = digitalRead(AUTO_TRIGGER_PIN);
    if (currentTriggerState == HIGH && lastTriggerState == LOW) {
        if (millis() - lastTriggerTime > DEBOUNCE_DELAY) {
            Serial.println("Digital trigger received on pin 3.");
            autoCycle();
            lastTriggerTime = millis();
        }
    }
    lastTriggerState = currentTriggerState;
    // Trigger autoCycle or step from serial
    if (Serial.available() > 0) {
        int input = Serial.parseInt();
        while (Serial.available() > 0) {
            Serial.read(); // Clear remaining buffer
        }
        if (input == 1) {
            autoCycle();
        } else if (input != 0) {
            Serial.print("Moving ");
            Serial.print(input);
            Serial.println(" steps...");
            moveStepper(input);
        }
        Serial.println("Enter new step count:");
    }
}