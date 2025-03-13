import pandas as pd
import sqlite3 as sql
import time

file = (pd.read_csv("users.csv", delimiter=',')).fillna("")
my_csv_data = file.values.tolist()
con = sql.connect("coffee_test.db")
con2=sql.connect("coffee_test_view.db")
print(con.total_changes)

cur2=con2.cursor()
cur = con.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS coffee_count (id INTEGER , date TEXT, nb_coffee INTEGER, price REAL)")
cur.execute("CREATE TABLE IF NOT EXISTS payement (id INTEGER, date TEXT, credit INTEGER, label TEXT, type INTEGER, already_taken INTEGER)")
cur.execute("CREATE TABLE IF NOT EXISTS current (id INTEGER PRIMARY KEY, name TEXT, surname TEXT, nickname TEXT, mail TEXT, id_badge TEXT, credit REAL, debit REAL, sold REAL)")
cur2.execute("CREATE TABLE IF NOT EXISTS view (name TEXT, surname TEXT, nickname TEXT, mail TEXT, sold REAL)")
print(con.total_changes)

for i in range(0, len(my_csv_data)) :
	debit=0.
	credit=0.
	sold=my_csv_data[i][5]
	if (my_csv_data[i][5]<0.):
		credit=abs(my_csv_data[i][5])
	else:
		debit=my_csv_data[i][5]
	print(i,my_csv_data[i][0],my_csv_data[i][1],my_csv_data[i][2],my_csv_data[i][3],my_csv_data[i][4],credit,debit,sold)
	cur.execute("INSERT INTO current VALUES (?,?,?,?,?,?,?,?,?)",(i,my_csv_data[i][0],my_csv_data[i][1],my_csv_data[i][2],my_csv_data[i][3],my_csv_data[i][4],credit,debit,sold))
	cur2.execute("INSERT INTO view VALUES (?,?,?,?,?)",(my_csv_data[i][0],my_csv_data[i][1],my_csv_data[i][2],my_csv_data[i][3],sold))
	print(con.total_changes)
cur.execute("SELECT * FROM current WHERE name = 'Caroline'")
rows=cur.fetchall()
for row in rows:
	print(row)
con.commit()
con.close()
con2.commit()
con2.close()
