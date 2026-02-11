import sqlite3

# This creates a file named 'my_website.db' automatically
connection = sqlite3.connect('my_website.db')
cursor = connection.cursor()

# Create a 'users' table
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        email TEXT NOT NULL
    )
''')

# Add a sample user so we have data to look at
cursor.execute("INSERT INTO users (username, email) VALUES ('AI_Learner', 'hello@world.com')")

connection.commit()
connection.close()

print("Database and table created successfully!")
