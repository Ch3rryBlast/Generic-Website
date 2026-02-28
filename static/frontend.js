import {useState, useContext, createContext} from 'react';


const CounterContext = createContext();

export function CounterProvider(props) {
  const [state, setState] = useState({
    edited: false,
    hot: false
  });
  return (
    <CounterContext.Provider
      value={{
        state,
        setState
      }}
    >
      {props.children}
    </CounterContext.Provider>
  );
}