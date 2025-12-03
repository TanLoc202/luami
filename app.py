# Nếu dùng FastAPI
@app.get("/health")
def health_check():
    return "OK"

# Nếu dùng Flask
@app.route("/health")
def health_check():
    return "OK"
