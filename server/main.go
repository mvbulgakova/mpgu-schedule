package main

import (
	"fmt"
	"log"
	"net/http"
	"time"
)

// handleHello отвечает текстом на GET /hello
func handleHello(w http.ResponseWriter, r *http.Request) {
	fmt.Fprintln(w, "Привет от Go-сервера!")
}

// handleGreet формирует приветствие с именем из query-параметра:
//
//	GET /greet?name=Мария → "Привет, Мария!"
func handleGreet(w http.ResponseWriter, r *http.Request) {
	name := r.URL.Query().Get("name")
	if name == "" {
		name = "Гость"
	}
	fmt.Fprintf(w, "Привет, %s!\n", name)
}

// handleForm показывает форму (GET) и обрабатывает отправку (POST)
func handleForm(w http.ResponseWriter, r *http.Request) {
	switch r.Method {
	case http.MethodGet:
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		fmt.Fprintln(w, `<!DOCTYPE html>
<html><body>
<form method="POST" action="/form">
  <label>Имя: <input type="text" name="username"></label>
  <button type="submit">Отправить</button>
</form>
</body></html>`)

	case http.MethodPost:
		if err := r.ParseForm(); err != nil {
			http.Error(w, "Ошибка разбора формы", http.StatusBadRequest)
			return
		}
		username := r.FormValue("username")
		if username == "" {
			username = "неизвестный"
		}
		fmt.Fprintf(w, "Форма получена. Имя: %s\n", username)

	default:
		http.Error(w, "Метод не поддерживается", http.StatusMethodNotAllowed)
	}
}

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/hello", handleHello)
	mux.HandleFunc("/greet", handleGreet)
	mux.HandleFunc("/form", handleForm)

	// Явная конфигурация сервера с таймаутами (защита от медленных клиентов)
	srv := &http.Server{
		Addr:         ":8080",
		Handler:      mux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 10 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	log.Println("Сервер запущен на http://localhost:8080")
	log.Println("  GET  /hello")
	log.Println("  GET  /greet?name=<имя>")
	log.Println("  GET  /form  — показать форму")
	log.Println("  POST /form  — обработать форму")

	if err := srv.ListenAndServe(); err != nil {
		log.Fatal(err)
	}
}
