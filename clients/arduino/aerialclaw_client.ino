/**
 * clients/arduino/aerialclaw_client.ino
 * AerialClaw ESP32 设备客户端示例
 *
 * 功能：
 *   1. 连接 WiFi
 *   2. HTTP POST 注册设备，获取 Token
 *   3. WebSocket 连接服务端（Socket.IO over WebSocket）
 *   4. 每 5 秒发送心跳
 *   5. 接收 device_action 指令 → 闪烁 LED → 回报结果
 *   6. 定期上报设备状态与传感器数据
 *
 * 依赖库（在 Arduino IDE 库管理器安装）：
 *   - ArduinoJson      by Benoit Blanchon  (v6.x)
 *   - arduinoWebSockets by Markus Sattler  (搜索 "WebSockets")
 *   - HTTPClient       (ESP32 内置)
 *   - WiFi             (ESP32 内置)
 *
 * 硬件：ESP32 开发板（任意型号）
 */

#include <WiFi.h>
#include <HTTPClient.h>
#include <WebSocketsClient.h>   // arduinoWebSockets
#include <ArduinoJson.h>

// ─────────────────────────────────────────────
//  用户配置区 — 修改这里的参数
// ─────────────────────────────────────────────

// WiFi 配置
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// AerialClaw 服务端配置
const char* SERVER_HOST = "192.168.1.100";   // 服务端 IP（不含 http://）
const int   SERVER_PORT = 5001;              // 服务端端口

// 设备配置
const char* DEVICE_ID   = "esp32_01";        // 设备唯一 ID
const char* DEVICE_TYPE = "SENSOR";          // UAV / UGV / ARM / SENSOR / CUSTOM

// 内置 LED 引脚（ESP32 通常是 GPIO2）
const int LED_PIN = 2;

// 心跳间隔（毫秒）
const unsigned long HEARTBEAT_INTERVAL_MS = 5000;

// ─────────────────────────────────────────────
//  全局变量
// ─────────────────────────────────────────────

WebSocketsClient wsClient;           // WebSocket 客户端
String g_token        = "";          // 注册后获取的 Token
bool   g_ws_connected = false;       // WebSocket 是否已连接并认证
unsigned long g_last_heartbeat = 0;  // 上次心跳时间
unsigned long g_last_state     = 0;  // 上次状态上报时间

// ─────────────────────────────────────────────
//  函数声明
// ─────────────────────────────────────────────

bool    connectWiFi();
bool    registerDevice();
void    connectWebSocket();
void    sendHeartbeat();
void    sendDeviceState();
void    sendActionResult(const String& actionId, bool success,
                         const String& message);
void    handleAction(const JsonObject& payload);
void    webSocketEvent(WStype_t type, uint8_t* payload, size_t length);
void    blinkLED(int times, int delayMs = 200);

// ─────────────────────────────────────────────
//  setup()
// ─────────────────────────────────────────────

void setup() {
    Serial.begin(115200);
    delay(500);

    Serial.println("\n====== AerialClaw ESP32 客户端 ======");

    // 初始化 LED
    pinMode(LED_PIN, OUTPUT);
    digitalWrite(LED_PIN, LOW);

    // 1. 连接 WiFi
    if (!connectWiFi()) {
        Serial.println("[错误] WiFi 连接失败，重启...");
        delay(3000);
        ESP.restart();
    }

    // 2. 注册到 AerialClaw 服务端
    if (!registerDevice()) {
        Serial.println("[错误] 设备注册失败，重启...");
        delay(3000);
        ESP.restart();
    }

    // 3. 建立 WebSocket 连接
    connectWebSocket();

    Serial.println("[初始化] 完成！进入主循环...");
    blinkLED(3);  // 3 次闪烁表示初始化成功
}

// ─────────────────────────────────────────────
//  loop()
// ─────────────────────────────────────────────

void loop() {
    // 处理 WebSocket 消息（必须放在 loop 里）
    wsClient.loop();

    unsigned long now = millis();

    // 每 5 秒发送心跳
    if (g_ws_connected && (now - g_last_heartbeat >= HEARTBEAT_INTERVAL_MS)) {
        sendHeartbeat();
        g_last_heartbeat = now;
    }

    // 每 10 秒上报一次设备状态（可根据需要缩短）
    if (g_ws_connected && (now - g_last_state >= 10000)) {
        sendDeviceState();
        g_last_state = now;
    }

    // 在这里读取传感器并上报，示例省略
    // 实际项目中在此读取 GPIO/I2C/SPI 数据并调用 sendSensorData()
}

// ─────────────────────────────────────────────
//  WiFi 连接
// ─────────────────────────────────────────────

bool connectWiFi() {
    Serial.printf("[WiFi] 连接到 %s ...\n", WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 20) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.printf("\n[WiFi] 已连接！IP: %s\n",
                      WiFi.localIP().toString().c_str());
        return true;
    }
    return false;
}

// ─────────────────────────────────────────────
//  HTTP 注册设备
// ─────────────────────────────────────────────

bool registerDevice() {
    HTTPClient http;
    String url = String("http://") + SERVER_HOST + ":" +
                 SERVER_PORT + "/api/device/register";

    Serial.printf("[注册] POST %s\n", url.c_str());
    http.begin(url);
    http.addHeader("Content-Type", "application/json");

    // 构造注册 JSON
    StaticJsonDocument<512> reqDoc;
    reqDoc["device_id"]   = DEVICE_ID;
    reqDoc["device_type"] = DEVICE_TYPE;
    reqDoc["protocol"]    = "http";

    // 能力列表（根据实际硬件修改）
    JsonArray caps = reqDoc.createNestedArray("capabilities");
    caps.add("sensor");

    // 传感器列表（根据实际硬件修改）
    JsonArray sensors = reqDoc.createNestedArray("sensors");
    sensors.add("temperature");
    sensors.add("humidity");

    // 元信息
    JsonObject meta = reqDoc.createNestedObject("metadata");
    meta["model"]    = "ESP32 DevKit";
    meta["firmware"] = "AerialClaw-Client-v1.0";

    String reqBody;
    serializeJson(reqDoc, reqBody);

    int httpCode = http.POST(reqBody);
    if (httpCode <= 0) {
        Serial.printf("[注册] 请求失败，HTTP 错误: %d\n", httpCode);
        http.end();
        return false;
    }

    String respBody = http.getString();
    http.end();

    // 解析响应
    StaticJsonDocument<256> respDoc;
    DeserializationError err = deserializeJson(respDoc, respBody);
    if (err) {
        Serial.printf("[注册] JSON 解析失败: %s\n", err.c_str());
        return false;
    }

    if (!respDoc["ok"].as<bool>()) {
        Serial.printf("[注册] 服务端拒绝: %s\n",
                      respDoc["error"].as<const char*>());
        return false;
    }

    g_token = respDoc["token"].as<String>();
    Serial.printf("[注册] 成功！Token: %s\n", g_token.c_str());
    return true;
}

// ─────────────────────────────────────────────
//  WebSocket 连接（Socket.IO 兼容）
// ─────────────────────────────────────────────

void connectWebSocket() {
    // Socket.IO 路径为 /socket.io/，带 Token 查询参数
    String path = "/socket.io/?token=" + g_token + "&EIO=4&transport=websocket";

    Serial.printf("[WS] 连接 %s:%d%s\n",
                  SERVER_HOST, SERVER_PORT, path.c_str());

    wsClient.begin(SERVER_HOST, SERVER_PORT, path);
    wsClient.onEvent(webSocketEvent);
    wsClient.setReconnectInterval(5000);   // 断线 5 秒后重连
}

// ─────────────────────────────────────────────
//  WebSocket 事件处理器
// ─────────────────────────────────────────────

void webSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
    switch (type) {

    case WStype_CONNECTED:
        Serial.println("[WS] WebSocket 已连接");
        // 发送 Socket.IO 握手（EIO4 协议）
        wsClient.sendTXT("40");           // Socket.IO connect packet
        break;

    case WStype_TEXT: {
        String msg = String((char*)payload);

        // Socket.IO EIO4 协议头处理
        // "0{...}" = 握手包，"2" = ping，"42[...]" = 事件
        if (msg.startsWith("0")) {
            // 握手完成后发送 device_connect 认证
            StaticJsonDocument<256> authDoc;
            authDoc["device_id"] = DEVICE_ID;
            authDoc["token"]     = g_token;
            String authData;
            serializeJson(authDoc, authData);
            String packet = "42[\"device_connect\"," + authData + "]";
            wsClient.sendTXT(packet);
            Serial.println("[WS] 已发送 device_connect 认证");

        } else if (msg == "2") {
            // Ping → 回复 Pong
            wsClient.sendTXT("3");

        } else if (msg.startsWith("42")) {
            // 事件消息，格式: 42["event_name", {...}]
            // 去掉 "42" 前缀
            String jsonPart = msg.substring(2);

            // 解析事件数组 ["event", data]
            StaticJsonDocument<1024> doc;
            DeserializationError err = deserializeJson(doc, jsonPart);
            if (err) {
                Serial.printf("[WS] JSON 解析失败: %s\n", err.c_str());
                break;
            }

            String eventName = doc[0].as<String>();

            if (eventName == "device_connected") {
                // 服务端确认认证
                bool ok = doc[1]["ok"].as<bool>();
                if (ok) {
                    g_ws_connected = true;
                    Serial.println("[WS] 认证成功，设备已上线！");
                    blinkLED(2);
                } else {
                    Serial.println("[WS] 认证失败！");
                }

            } else if (eventName == "device_action") {
                // 收到指令，执行并回报
                handleAction(doc[1].as<JsonObject>());

            } else if (eventName == "heartbeat_ack") {
                // 心跳确认，静默处理
            } else {
                Serial.printf("[WS] 收到未知事件: %s\n", eventName.c_str());
            }
        }
        break;
    }

    case WStype_DISCONNECTED:
        g_ws_connected = false;
        Serial.println("[WS] WebSocket 已断开，等待重连...");
        break;

    case WStype_ERROR:
        Serial.println("[WS] WebSocket 错误");
        break;

    default:
        break;
    }
}

// ─────────────────────────────────────────────
//  发送心跳
// ─────────────────────────────────────────────

void sendHeartbeat() {
    StaticJsonDocument<128> doc;
    doc["device_id"] = DEVICE_ID;
    doc["timestamp"] = millis() / 1000.0;

    String data;
    serializeJson(doc, data);
    String packet = "42[\"heartbeat\"," + data + "]";
    wsClient.sendTXT(packet);

    Serial.printf("[心跳] 已发送 (uptime: %lums)\n", millis());
}

// ─────────────────────────────────────────────
//  上报设备状态
// ─────────────────────────────────────────────

void sendDeviceState() {
    StaticJsonDocument<256> doc;
    doc["device_id"] = DEVICE_ID;
    doc["timestamp"] = millis() / 1000.0;
    doc["status"]    = "idle";
    doc["battery"]   = 100;              // 实际项目中读取电池 ADC

    String data;
    serializeJson(doc, data);
    String packet = "42[\"device_state\"," + data + "]";
    wsClient.sendTXT(packet);

    Serial.println("[状态] 已上报设备状态");
}

// ─────────────────────────────────────────────
//  处理 device_action 指令
// ─────────────────────────────────────────────

void handleAction(const JsonObject& payload) {
    String actionId = payload["action_id"].as<String>();
    String action   = payload["action"].as<String>();

    Serial.printf("[指令] 收到: action_id=%s, action=%s\n",
                  actionId.c_str(), action.c_str());

    // ── 根据 action 执行不同逻辑 ──────────────────────
    bool   success = true;
    String message = "";

    if (action == "blink") {
        // 闪灯示例
        int times = payload["params"]["times"] | 3;
        blinkLED(times);
        message = "闪烁 " + String(times) + " 次完成";

    } else if (action == "get_status") {
        // 返回当前状态
        message = "在线，正常运行";

    } else if (action == "reset") {
        // 重启设备
        message = "即将重启";
        sendActionResult(actionId, true, message);
        delay(500);
        ESP.restart();
        return;  // restart() 不会走到这里

    } else {
        // 未知指令
        success = false;
        message = "未知指令: " + action;
        Serial.printf("[指令] 未知: %s\n", action.c_str());
    }

    // 回报执行结果
    sendActionResult(actionId, success, message);
}

// ─────────────────────────────────────────────
//  回报 action_result
// ─────────────────────────────────────────────

void sendActionResult(const String& actionId, bool success,
                      const String& message) {
    StaticJsonDocument<256> doc;
    doc["action_id"] = actionId;
    doc["device_id"] = DEVICE_ID;
    doc["success"]   = success;
    doc["message"]   = message;

    String data;
    serializeJson(doc, data);
    String packet = "42[\"action_result\"," + data + "]";
    wsClient.sendTXT(packet);

    Serial.printf("[结果] action_id=%s success=%s msg=%s\n",
                  actionId.c_str(),
                  success ? "true" : "false",
                  message.c_str());
}

// ─────────────────────────────────────────────
//  辅助：LED 闪烁
// ─────────────────────────────────────────────

void blinkLED(int times, int delayMs) {
    for (int i = 0; i < times; i++) {
        digitalWrite(LED_PIN, HIGH);
        delay(delayMs);
        digitalWrite(LED_PIN, LOW);
        delay(delayMs);
    }
}
