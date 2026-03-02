# Muy optimista
import sqlite3
import pandas as pd
from fuchitools.datetimes import to_datetime


class SqliteConnection(sqlite3.Connection):
    def __init__(self, path, *args, **kwargs):
        super().__init__(path, *args, **kwargs)
        self.path = path


def is_conn(conn):
    return isinstance(conn, sqlite3.Connection) 


def connection(conn):
    """
    Si conn es una cadena se conecta a la bbdd con ese nombre y devuelve 
    la conexión, si no devuelve conn
    """
    if is_conn(conn):
        return conn, True
    
    return SqliteConnection(conn), False
    return sqlite3.connect(conn), False


def conn_or_db(func, *args, **kwargs):
    
    def wrapper(*args, **kwargs):
        conn, is_conn = connection(args[0])
        
        try:
            salida = func(*([conn] + list(args[1:])), **kwargs)
        
        finally:
            if not is_conn:
                conn.commit()
                conn.close() 
        
        return salida
        
    return wrapper


def datetime_to_sqlite(x):
    try:
        return x.strftime("%Y-%m-%d 00:00:00")
    except:
        return None


def to_sqlite_dt(x):
    return datetime_to_sqlite(to_datetime(x))


def df_datetimes_to_sqlite(df, dt_columns):
    for col in dt_columns:
        df.loc[:, col] = df[col].apply(datetime_to_sqlite)


@conn_or_db
def exe(conn, *sql):

    def exe_one(conn, sql_or_tuple):
        if isinstance(sql_or_tuple, str):
            return conn.execute(sql_or_tuple)
        else:
            return conn.execute(sql_or_tuple[0], sql_or_tuple[1])

    
    if len(sql)>1:
        #exe_one(conn, "BEGIN;")
        try:
            for command in sql:
                salida = exe_one(conn, command)
            #exe_one(conn, "COMMIT;")
            return salida
        
        except ValueError:
            print("Error en sql")
            exe_one(conn, "ROLLBACK;") 
            return None 
    
    else:    
        return exe_one(conn, sql[0])
   

@conn_or_db
def table_exists(conn, table):
    
    try:
        return conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?;", (table, )).fetchone()[0] == 1
        
    except:
        return False


@conn_or_db
def df_to_sql(conn, df, table, index=False, if_exists='fail'):
    df.to_sql(table, conn, index=index, if_exists=if_exists)
        

def sheet_to_sqlite(excel_filename, db_filename, table_name, sheet_name=None):
    
    wb = pd.read_excel(excel_filename, sheet_name=None) # devuelve todas las hojas como un OrderedDictionary
   
    if len(wb) != 1:
        raise ValueError("No has identificado la hoja a cargar")
    
    with sqlite3.connect(db_filename) as conn:
        (wb.popitem()[1]).to_sql(table_name,conn, index=False)
    
    conn.close()


def load_excel(excel_filename, sheet_name=None):

    df = pd.read_excel(excel_filename, sheet_name=sheet_name) # si sheet_name = None devuelve todas las hojas como un OrderedDictionary
    
    if sheet_name is None:      
        df = (df.popitem()[1])
    
    df = df.loc[pd.notna(df.iloc[:,0]), :]
    
    return df

#*************** Variables ************************************    

@conn_or_db 
def set_variable(conn, variable, value, table="variables"):
  
    if not table_exists(conn, table):
        exe(conn,
            f"""
            CREATE TABLE {table} (variable CHAR PRIMARY KEY
                                    CONSTRAINT variable_unica UNIQUE ON CONFLICT REPLACE
                                    NOT NULL,
                                    value) WITHOUT ROWID;
            """)
            
    exe(conn,
        (f"INSERT INTO {table} (variable, value) VALUES (?, ?);",(variable, value)))

    return True


@conn_or_db 
def get_variable(conn, variable, table="variables"):
    return conn.execute(f"SELECT value FROM {table} WHERE variable=?;", (variable, )).fetchone()[0]


@conn_or_db 
def delete_variable(conn, variable, table="variables"):
    return conn.execute(f"DELETE FROM {table} WHERE variable=?;", (variable, ))

@conn_or_db 
def delete_all_variables(conn, table="variables"):
    return conn.execute(f"DELETE FROM {table};")

@conn_or_db
def df_from_sqlite(conn, sql, params=None, parse_dates=None):   
    return pd.read_sql(sql, conn, params=params, parse_dates=parse_dates)



