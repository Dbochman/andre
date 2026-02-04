CREATE TABLE IF NOT EXISTS userdata (
username text,
email text default('@'),
age integer,
primary key(username),
constraint ageCheck CHECK (age>= 0 AND age<=200)
);

INSERT INTO userdata (username, email, age) VALUES ('gpusr', 'golden@path', 42);


