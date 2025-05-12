#include <Wire.h>
#include <Adafruit_MLX90614.h>
#include <Servo.h>

Adafruit_MLX90614 mlx = Adafruit_MLX90614();
Servo myServo;
String command = "";

void setup() {
  Serial.begin(9600);
  mlx.begin();
  myServo.attach(9); 
}

void loop() {
  Serial.println(mlx.readObjectTempC());

  if (Serial.available()) 
  {
    command = Serial.readStringUntil('\n');
    command.trim();

    if (command == "servo") 
    {
      //myServo.write(90);
      myServo.wirteMicroseconds(1450);
      delay(500);
      myServo.wirteMicroseconds(1550);
      delay(500);

    }
  }
  else
  {
    delay(1000); 
  }
}
