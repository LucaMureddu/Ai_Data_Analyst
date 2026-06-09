"""
Genera dati_test.csv — dataset fittizio per testare Data-Whisperer.
Contiene: Data, Sede, Prodotto, Fatturato, Quantita, Costo, Margine
"""
import csv
import datetime
import os
import random

random.seed(42)
sedi     = ["Milano", "Roma", "Napoli", "Torino", "Bologna"]
prodotti = ["Laptop", "Monitor", "Tastiera", "Mouse", "Cuffie", "Webcam"]
out      = os.path.join(os.path.dirname(__file__), "dati_test.csv")

rows = [["Data","Sede","Prodotto","Fatturato","Quantita","Costo","Margine"]]
start = datetime.date(2023, 1, 1)
for i in range(300):
    d    = start + datetime.timedelta(days=random.randint(0, 729))  # 2023-2024
    sede = random.choice(sedi)
    prod = random.choice(prodotti)
    qty  = random.randint(1, 50)
    fat  = round(random.uniform(200, 4000) * qty / 10, 2)
    cost = round(fat * random.uniform(0.45, 0.75), 2)
    marg = round(fat - cost, 2)
    rows.append([d.strftime("%Y-%m-%d"), sede, prod, fat, qty, cost, marg])

with open(out, "w", newline="") as f:
    csv.writer(f).writerows(rows)

print(f"Creato: {out}  ({len(rows)-1} righe)")
print("Colonne: Data, Sede, Prodotto, Fatturato, Quantita, Costo, Margine")
