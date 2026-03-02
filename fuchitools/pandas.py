import pandas as pd
from functools import reduce

def load_excel(excel_filename, sheet_name=None):
    df = pd.read_excel(excel_filename, sheet_name=sheet_name) # si sheet_name = None devuelve todas las hojas como un OrderedDictionary  
    if sheet_name is None:      
        df = (df.popitem()[1])   
    df = df.loc[pd.notna(df.iloc[:,0]), :]   
    return df


def join_dataframes(lis, on=None):
    # Si on no especificado o None, por index 
    def join_two(x, y):
        z = x.join(y, how="outer", on=on)
        return z.loc[:, ~z.columns.duplicated()]
        
    return reduce(lambda a, b: join_two(a,b), lis)