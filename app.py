from flask import Flask, render_template, request, redirect
import sqlite3
import csv
import chess.pgn
from datetime import datetime
app=Flask(__name__,template_folder='templates',static_folder='static')

def db():
    conn = sqlite3.connect("data/main.db")
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS players (
        name TEXT NOT NULL,
        rating INTEGER NOT NULL,
        ccr REAL NOT NULL,
        tourns INTEGER NOT NULL,
        podiums INTEGER NOT NULL
    )
    ''')
    conn.commit()

    c.execute('''
    CREATE TABLE IF NOT EXISTS tourns (
        name TEXT NOT NULL,
        winner TEXT NOT NULL,
        date DATE NOT NULL,
        players INTEGER NOT NULL,
        weight INTEGER NOT NULL,
        pgn TEXT
    )
    ''')
    conn.commit()
    conn.close()

def ccr(w,r,p,pct,perf):
    try:
        ccr=p*0.1+0.000003*perf**2-0.02*pct+0.2*r
        ccr*=w/5
    except Exception as e: ccr=0.0
    return round(ccr,3)


def ccrdecay(ccr, weight, tournament_date):
    try:
        today = datetime.now()
        days_elapsed = (today - tournament_date).days
        early_decay_days = min(days_elapsed, int(weight * 15))
        early_decay = early_decay_days * 0.005
        late_decay_days = max(0, days_elapsed - int(weight * 15))
        late_decay = late_decay_days * 0.1
        total_decay = early_decay + late_decay
        decayed_ccr = max(0, ccr - total_decay)  
        return decayed_ccr
    except Exception as e:
        print(f"Error calculating CCR decay: {e}")
        return round(ccr,3)


def parse_csv(file):
    try:
        csv_file = file.stream.read().decode('utf-8').splitlines()
        csv_reader = csv.DictReader(csv_file)
        rows = [row for row in csv_reader]
        return rows
    except FileNotFoundError:
        print('File not found')
        return []
    except Exception as e:
        print(f"An error occurred: {e}")
        return []
    
def updateplayer(rows, pgn,w,p):
    try:
        player_stats = {player['Username']: {'games': 0, 'wins': 0} for player in rows}
        pgn_content = pgn.stream.read().decode('utf-8').splitlines()
        from io import StringIO
        pgn_file = StringIO("\n".join(pgn_content))
        while True:
            game = chess.pgn.read_game(pgn_file)
            if game is None:
                break
            white_player = game.headers.get("White", None)
            black_player = game.headers.get("Black", None)
            result = game.headers.get("Result", None)
            if white_player in player_stats:
                player_stats[white_player]['games'] += 1
                if result == "1-0":
                    player_stats[white_player]['wins'] += 1
            if black_player in player_stats:
                player_stats[black_player]['games'] += 1
                if result == "0-1":
                    player_stats[black_player]['wins'] += 1
        for player in rows:
            username = player['Username']
            games = player_stats[username]['games']
            wins = player_stats[username]['wins']
            player['games'] = games
            player['winrate'] = round((wins / games) * 100, 2) if games > 0 else 0
            if games==0: 
                player['ccr']=0.0
                player['pct']=(p-int(player['Rank']))*100/p
                player['Performance']=0
            else:
                pct=round((p-int(player['Rank']))*100/p,2)
                player['pct']=pct
                try:
                    player['ccr']=ccr(w,player['winrate'],int(player['Score']),pct,int(player['Performance']))
                except Exception as e:
                    player['ccr']=0.0
                    return redirect('/')
    except Exception as e:
        print('Relay Error from PGN parsing:', e,pct,type(pct))
    return rows

def updateccr():
    try:
        players_conn = sqlite3.connect('data/players.db')
        main_conn = sqlite3.connect('data/main.db')
        players_cursor = players_conn.cursor()
        main_cursor = main_conn.cursor()
        main_cursor.execute('SELECT name FROM players')
        all_players = main_cursor.fetchall()
        for player in all_players:
            username = player[0]
            players_cursor.execute(f'SELECT ccr, date, weight FROM "{username}"')
            tournaments = players_cursor.fetchall()
            total_ccr = 0.0
            for tournament in tournaments:
                raw_ccr, tournament_date, weight = tournament
                tournament_date = datetime.strptime(tournament_date, '%Y-%m-%d')
                decayed_ccr = ccrdecay(raw_ccr, weight, tournament_date)
                total_ccr += decayed_ccr
            main_cursor.execute('''
                UPDATE players
                SET ccr = ?
                WHERE name = ?
            ''', (round(total_ccr, 3), username))
        main_conn.commit()
        players_conn.close()
        main_conn.close()
    except Exception as e:
        print(f"An error occurred while updating CCR with decay: {e}")

def updatedb(rows, tournament_date, tournament_name, weight,winner,players,pgn):
    try:
        players_conn = sqlite3.connect('data/players.db')
        players_cursor = players_conn.cursor()
        for row in rows:
            username = row['Username']
            rating = row['Rating']
            raw_ccr = row['ccr']
            games = row['games']
            winrate = row['winrate']
            podium = 1 if row['pct'] >= 85 else 0
            players_cursor.execute(f'''
                CREATE TABLE IF NOT EXISTS "{username}" (
                    rating INTEGER,
                    ccr REAL,
                    tourn TEXT,
                    games INTEGER,
                    winrate REAL,
                    date DATE,
                    podium INTEGER,
                    weight INTEGER
                )
            ''')

            players_cursor.execute(f'''
                INSERT INTO "{username}" (rating, ccr, tourn, games, winrate, date, podium, weight)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (rating, raw_ccr, tournament_name, games, winrate, tournament_date, podium, weight))

        players_conn.commit()
        players_conn.close()
        main_conn = sqlite3.connect('data/main.db')
        main_cursor = main_conn.cursor()

        for row in rows:
            username = row['Username']
            rating = row['Rating']

            players_conn = sqlite3.connect('data/players.db')
            players_cursor = players_conn.cursor()

            players_cursor.execute(f'SELECT ccr, date, weight FROM "{username}"')
            all_entries = players_cursor.fetchall()

            total_ccr = 0
            for entry_ccr, entry_date, entry_weight in all_entries:
                entry_date_obj = datetime.strptime(entry_date, '%Y-%m-%d')
                total_ccr += ccrdecay(entry_ccr, entry_weight, entry_date_obj)

            players_cursor.execute(f'SELECT COUNT(*) FROM "{username}"')
            tourns = players_cursor.fetchone()[0]

            players_cursor.execute(f'SELECT SUM(podium) FROM "{username}"')
            total_podiums = players_cursor.fetchone()[0]

            players_conn.close()

            main_cursor.execute('SELECT * FROM players WHERE name = ?', (username,))
            result = main_cursor.fetchone()

            if result:
                main_cursor.execute('''
                    UPDATE players
                    SET rating = ?, ccr = ?, tourns = ?, podiums = ?
                    WHERE name = ?
                ''', (rating, total_ccr, tourns, total_podiums, username))
            else:
                main_cursor.execute('''
                    INSERT INTO players (name, rating, ccr, tourns, podiums)
                    VALUES (?, ?, ?, ?, ?)
                ''', (username, rating, total_ccr, tourns, total_podiums))

        main_conn.commit()
        main_cursor.execute('INSERT INTO tourns (name,winner,date,players,weight,pgn) VALUES (?,?,?,?,?,?)',(tournament_name,winner,tournament_date,players,weight,pgn))
        main_conn.commit()
        main_conn.close()

        print("Database updated successfully.")

    except Exception as e:
        print(f"An error occurred: {e}")




@app.route('/',methods=['GET','POST'])
def index():
    if request.method=='GET':
        return render_template('index.html')
    elif request.method=='POST':
        button=request.form['button']
        if button=='addtourn': return redirect('/add')
        elif button=='viewplayers':return redirect('/viewplayers')
        elif button=='tutorial': return redirect('/guide')
        elif button=='iconic': return redirect('/iconic')

@app.route('/add',methods=['GET','POST'])
def add():
    if request.method=='GET':
        return render_template('add.html')
    elif request.method=='POST':
        csvfile=request.files['csvfile']
        rows=parse_csv(csvfile)
        w=int(request.form['weight'])
        n=int(request.form['players'])
        winner=request.form['winner']
        pgniconic=request.files['pgniconic'].stream.read().decode('utf-8')
        date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
        for row in rows:
            row.setdefault('games',0)
            row.setdefault('winrate',0)
            row.setdefault('ccr',0.0)
        pgnfile=request.files['pgnfile']
        try:
            updateplayer(rows,pgnfile,w,n)
        except Exception as e: print(e)
        updatedb(rows,date,request.form['name'],w,winner,n,pgniconic)
        return render_template('add.html',status=1)



@app.route('/viewplayers')
def viewplayers():
    try:
        updateccr()
        conn=sqlite3.connect('data/main.db')
        c=conn.cursor()
        c.execute('SELECT * FROM players ORDER BY ccr DESC')
        rows=c.fetchall()
        conn.close()
        return render_template('viewplayers.html',data=rows)
    except Exception as e: 
        print('Relay Error from ViewPlayers: ',e)
        return render_template('viewplayers.html',data=())


if __name__=='__main__':
    db()
    app.run(host='0.0.0.0',port=5555,debug=True)