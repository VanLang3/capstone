import pygame
import time
import json
import paho.mqtt.client as mqtt
from collections import deque

# --- CONFIGURATION ---
MQTT_BROKER = "test.mosquitto.org"
MQTT_TOPIC = "nissan_leaf/teleop/control"
LATENCY_WINDOW = 20  # Sample size for latency averaging

# --- LATENCY TRACKING ---
latency_history = deque(maxlen=LATENCY_WINDOW)
iteration_count = 0

# --- SETUP PYGAME (THE DRIVER) ---
pygame.init()
pygame.joystick.init()

# Check if the wheel is plugged in
if pygame.joystick.get_count() == 0:
    print("❌ ERROR: No G29 Detected.")
    print("   -> Check your USB-C adapter.")
    print("   -> Ensure the switch on top of the wheel is set to 'PS3'.")
    exit()

# Initialize the first joystick found (The G29)
wheel = pygame.joystick.Joystick(0)
wheel.init()

print(f"✅ CONNECTED: {wheel.get_name()}")
print("   -> Listening for steering events...")
print("   -> Latency monitoring ACTIVE\n")

# --- SETUP MQTT (THE SENDER) ---
print("🔌 Attempting MQTT connection...")
try:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_BROKER, 1883, 60)
    client.loop_start()
    print("✅ MQTT Connected to test.mosquitto.org\n")
except Exception as e:
    print(f"⚠️ MQTT Connection Error: {e}")
    print("⚠️ Continuing without MQTT (will still read wheel data)\n")
    client = None

try:
    while True:
        try:
            loop_start = time.time()
            
            # 1. Pump the Event Loop (Required by Pygame to read hardware)
            pygame.event.pump()
            read_start = time.time()

            # 2. Read Steering (Axis 0)
            raw_steering = wheel.get_axis(0)

            # 3. Convert to 16-bit Integer (-32768 to 32767)
            steering_16bit = int(raw_steering * 32767)

            # 4. Read Pedals (Axes vary by OS, usually 2 and 3 on Mac)
            throttle_val = wheel.get_axis(2) 
            brake_val = wheel.get_axis(3)
            
            read_time = (time.time() - read_start) * 1000  # Convert to ms

            # Normalize pedals to 0-255 (8-bit)
            throttle_8bit = int((throttle_val + 1) * 127.5)
            brake_8bit = int((brake_val + 1) * 127.5)

            # 5. Create the Payload
            payload = {
                "steer": steering_16bit,
                "accel": throttle_8bit,
                "brake": brake_8bit
            }
            
            publish_start = time.time()
            # 6. Send to ESP32
            if client:
                client.publish(MQTT_TOPIC, json.dumps(payload))
            publish_time = (time.time() - publish_start) * 1000  # Convert to ms

            # Total latency from input read to transmission complete
            total_latency = (time.time() - loop_start) * 1000  # Convert to ms
            latency_history.append(total_latency)
            iteration_count += 1

            # Print every transmission with latency details
            print(f"Sending: {payload} | Read: {read_time:.2f}ms | Publish: {publish_time:.2f}ms | Loop: {total_latency:.2f}ms")

            # Calculate average latency every 20 iterations
            if iteration_count % 20 == 0 and iteration_count > 0:
                avg_latency = sum(latency_history) / len(latency_history)
                max_latency = max(latency_history)
                min_latency = min(latency_history)
                print(f"📊 LATENCY FEEDBACK:")
                print(f"   Read Time: {read_time:.2f}ms | Publish Time: {publish_time:.2f}ms")
                print(f"   Avg Loop: {avg_latency:.2f}ms | Max: {max_latency:.2f}ms | Min: {min_latency:.2f}ms")
                print(f"   Steer: {steering_16bit:6d} | Accel: {throttle_8bit:3d} | Brake: {brake_8bit:3d}")
                print("---")

            # 7. Maintain 100Hz Frequency
            sleep_time = 0.01 - (time.time() - loop_start)
            if sleep_time > 0:
                time.sleep(sleep_time)
        except Exception as loop_error:
            print(f"❌ LOOP ERROR: {loop_error}")
            import traceback
            traceback.print_exc()
            break

except KeyboardInterrupt:
    print("\n🛑 STOPPING: Disconnecting from wheel and cloud.")
    if latency_history:
        print(f"\n📊 FINAL LATENCY STATS (over {len(latency_history)} samples):")
        print(f"   Average: {sum(latency_history)/len(latency_history):.2f}ms")
        print(f"   Max: {max(latency_history):.2f}ms")
        print(f"   Min: {min(latency_history):.2f}ms")
    if client:
        client.disconnect()